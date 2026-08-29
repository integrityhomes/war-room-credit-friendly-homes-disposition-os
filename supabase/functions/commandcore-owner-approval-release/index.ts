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
      service: "commandcore-owner-approval-release",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  try {
    const [offers, documents, tasks] = await Promise.all([
      listEntity(url, key, "offers"),
      listEntity(url, key, "documents"),
      listEntity(url, key, "tasks"),
    ]);
    const existingKeys = new Set(tasks.map((task) => text(task.external_id)).filter(Boolean));
    const results: Row[] = [];

    for (const offer of offers) {
      if (text(offer.status) !== "owner_approved" || offer.external_action_started === true) continue;
      const offerId = text(offer.id);
      const dealId = text(links(offer).deal_id || offer.deal_id);
      const externalId = `owner-approved-offer-${offerId}-prepare-contract`;
      if (!existingKeys.has(externalId)) {
        await upsert(url, key, "tasks", {
          source: "commandcore-owner-approval-release",
          external_id: externalId,
          task_type: "deal_lifecycle_request",
          work_type: "prepare_contract",
          title: "Prepare contract after owner-approved offer",
          status: "open",
          priority: "high",
          owner_approval_verified: true,
          legal_terms_generated: false,
          external_action_started: false,
          links: { deal_id: dealId || null, offer_id: offerId || null },
        });
        existingKeys.add(externalId);
      }
      await upsert(url, key, "offers", { ...offer, approval_release_status: "released_to_internal_contract_prep", approval_released_at: new Date().toISOString(), external_action_started: false });
      results.push({ entity: "offers", id: offerId, next_step: "prepare_contract", deal_id: dealId });
    }

    for (const document of documents) {
      if (text(document.status) !== "owner_approved" || document.external_action_started === true) continue;
      const documentId = text(document.id);
      const dealId = text(links(document).deal_id || document.deal_id);
      const externalId = `owner-approved-document-${documentId}-internal-next-step`;
      if (!existingKeys.has(externalId)) {
        await upsert(url, key, "tasks", {
          source: "commandcore-owner-approval-release",
          external_id: externalId,
          task_type: "owner_approved_document_next_step",
          title: "Review approved document for next controlled step",
          status: "open",
          priority: "high",
          owner_approval_verified: true,
          external_action_started: false,
          links: { deal_id: dealId || null, document_id: documentId || null },
        });
        existingKeys.add(externalId);
      }
      await upsert(url, key, "documents", { ...document, approval_release_status: "released_to_internal_next_step", approval_released_at: new Date().toISOString(), external_action_started: false });
      results.push({ entity: "documents", id: documentId, next_step: "internal_review", deal_id: dealId });
    }

    return json(200, { ok: true, released_count: results.length, results, external_action_started: false });
  } catch (error) {
    console.error("Owner approval release failed", error);
    return json(503, { ok: false, error: error instanceof Error ? error.message : "owner_approval_release_unavailable", external_action_started: false });
  }
});
