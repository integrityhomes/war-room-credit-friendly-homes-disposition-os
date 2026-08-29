const SERVICE_VERSION = "2026-08-29.1";

type Row = Record<string, unknown>;

function text(value: unknown): string { return String(value ?? "").trim(); }
function obj(value: unknown): Row { return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {}; }
function links(row: Row): Row { return obj(row.links); }
function json(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let i = 0; i < left.length; i += 1) difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return difference === 0;
}
function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const authorization = req.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}
function verifiedExecutedContract(document: Row): boolean {
  const status = text(document.status).toLowerCase();
  const type = text(document.document_type).toLowerCase();
  return new Set(["executed", "fully_executed", "signed_executed"]).has(status) &&
    new Set(["executed_contract", "signed_contract"]).has(type) &&
    document.execution_verified === true &&
    document.signed_document_attached === true &&
    Boolean(text(document.executed_at));
}
async function crmCall(url: string, key: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `crm_call_failed_${response.status}`);
  return parsed;
}
async function listEntity(url: string, key: string, entity: string): Promise<Row[]> {
  const result = await crmCall(url, key, { action: "list", entity, limit: 500 });
  return Array.isArray(result.records) ? result.records.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Row[] : [];
}
async function upsert(url: string, key: string, entity: string, record: Row): Promise<Row> {
  const result = await crmCall(url, key, { action: "upsert", entity, record });
  return obj(result.record);
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return json(200, {
      ok: true,
      service: "commandcore-executed-contract-handoff",
      version: SERVICE_VERSION,
      status: "healthy",
      execution_evidence_required: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  try {
    const [documents, tasks] = await Promise.all([listEntity(url, key, "documents"), listEntity(url, key, "tasks")]);
    const existingTaskKeys = new Set(tasks.map((task) => text(task.external_id)).filter(Boolean));
    const candidates = documents.filter((document) => verifiedExecutedContract(document) && text(document.execution_handoff_status) !== "released_to_title_closing");
    const results: Row[] = [];

    for (const document of candidates) {
      const documentId = text(document.id);
      const dealId = text(links(document).deal_id || document.deal_id);
      if (!dealId) {
        results.push({ document_id: documentId, status: "blocked_missing_deal_link" });
        continue;
      }
      const externalId = `executed-contract-${documentId}-title-closing`;
      if (!existingTaskKeys.has(externalId)) {
        await upsert(url, key, "tasks", {
          source: "commandcore-executed-contract-handoff",
          external_id: externalId,
          task_type: "deal_lifecycle_request",
          work_type: "title_closing",
          title: "Open title and closing from verified executed contract",
          status: "open",
          priority: "high",
          execution_verified: true,
          signed_document_attached: true,
          external_action_started: false,
          links: { deal_id: dealId, document_id: documentId },
        });
        existingTaskKeys.add(externalId);
      }
      await upsert(url, key, "activities", {
        source: "commandcore-executed-contract-handoff",
        external_id: `executed-contract-handoff-${documentId}`,
        activity_type: "executed_contract_verified",
        title: "Executed contract verified; title/closing work opened",
        summary: "CommandCore verified explicit execution evidence and opened internal title/closing work.",
        occurred_at: new Date().toISOString(),
        details: { execution_verified: true, signed_document_attached: true, external_action_started: false },
        links: { deal_id: dealId, document_id: documentId },
      });
      await upsert(url, key, "documents", {
        ...document,
        execution_handoff_status: "released_to_title_closing",
        execution_handed_off_at: new Date().toISOString(),
        external_action_started: false,
      });
      results.push({ document_id: documentId, deal_id: dealId, status: "released_to_title_closing" });
    }

    return json(200, {
      ok: true,
      candidate_count: candidates.length,
      released_count: results.filter((item) => item.status === "released_to_title_closing").length,
      results,
      execution_evidence_required: true,
      external_action_started: false,
    });
  } catch (error) {
    console.error("Executed contract handoff failed", error);
    return json(503, { ok: false, error: error instanceof Error ? error.message : "executed_contract_handoff_unavailable", external_action_started: false });
  }
});
