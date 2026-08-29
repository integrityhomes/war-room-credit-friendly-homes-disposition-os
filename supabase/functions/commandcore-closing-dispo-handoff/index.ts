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
function verifiedClosing(transaction: Row): boolean {
  const status = text(transaction.status).toLowerCase();
  const type = text(transaction.transaction_type).toLowerCase();
  return new Set(["closed", "completed", "settled"]).has(status) &&
    new Set(["acquisition_closing", "purchase_closing", "closing"]).has(type) &&
    transaction.closing_verified === true &&
    transaction.ownership_or_control_confirmed === true &&
    Boolean(text(transaction.closed_at));
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
      service: "commandcore-closing-dispo-handoff",
      version: SERVICE_VERSION,
      status: "healthy",
      closing_evidence_required: true,
      ownership_or_control_confirmation_required: true,
      marketing_execution_started: false,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  try {
    const [transactions, tasks] = await Promise.all([listEntity(url, key, "transactions"), listEntity(url, key, "tasks")]);
    const existingTaskKeys = new Set(tasks.map((task) => text(task.external_id)).filter(Boolean));
    const candidates = transactions.filter((transaction) =>
      verifiedClosing(transaction) && text(transaction.dispo_handoff_status) !== "released_to_marketing_dispo"
    );
    const results: Row[] = [];

    for (const transaction of candidates) {
      const transactionId = text(transaction.id);
      const dealId = text(links(transaction).deal_id || transaction.deal_id);
      if (!dealId) {
        results.push({ transaction_id: transactionId, status: "blocked_missing_deal_link" });
        continue;
      }

      const externalId = `verified-closing-${transactionId}-marketing-dispo`;
      if (!existingTaskKeys.has(externalId)) {
        await upsert(url, key, "tasks", {
          source: "commandcore-closing-dispo-handoff",
          external_id: externalId,
          task_type: "deal_lifecycle_request",
          work_type: "marketing_dispo",
          title: "Prepare disposition after verified acquisition closing",
          status: "open",
          priority: "medium",
          closing_verified: true,
          ownership_or_control_confirmed: true,
          external_action_started: false,
          marketing_execution_started: false,
          links: { deal_id: dealId, transaction_id: transactionId },
        });
        existingTaskKeys.add(externalId);
      }

      await upsert(url, key, "activities", {
        source: "commandcore-closing-dispo-handoff",
        external_id: `closing-dispo-handoff-${transactionId}`,
        activity_type: "closing_verified_dispo_opened",
        title: "Closing verified; marketing/disposition work opened",
        summary: "CommandCore verified the acquisition closing and ownership/control evidence, then opened internal disposition preparation.",
        occurred_at: new Date().toISOString(),
        details: {
          closing_verified: true,
          ownership_or_control_confirmed: true,
          marketing_execution_started: false,
          external_action_started: false,
        },
        links: { deal_id: dealId, transaction_id: transactionId },
      });

      await upsert(url, key, "transactions", {
        ...transaction,
        dispo_handoff_status: "released_to_marketing_dispo",
        dispo_handed_off_at: new Date().toISOString(),
        marketing_execution_started: false,
        external_action_started: false,
      });

      results.push({ transaction_id: transactionId, deal_id: dealId, status: "released_to_marketing_dispo" });
    }

    return json(200, {
      ok: true,
      candidate_count: candidates.length,
      released_count: results.filter((item) => item.status === "released_to_marketing_dispo").length,
      results,
      closing_evidence_required: true,
      marketing_execution_started: false,
      external_action_started: false,
    });
  } catch (error) {
    console.error("Closing to disposition handoff failed", error);
    return json(503, {
      ok: false,
      error: error instanceof Error ? error.message : "closing_dispo_handoff_unavailable",
      marketing_execution_started: false,
      external_action_started: false,
    });
  }
});
