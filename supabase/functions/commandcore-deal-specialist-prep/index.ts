const SERVICE_VERSION = "2026-08-29.1";
const MAX_BODY_BYTES = 32 * 1024;

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function obj(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function links(record: Row): Row {
  return obj(record.links);
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const authorization = req.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function isOpen(record: Row): boolean {
  return !new Set(["done", "completed", "closed", "cancelled", "canceled"]).has(text(record.status).toLowerCase());
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
  return Array.isArray(result.records)
    ? result.records.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Row[]
    : [];
}

async function upsertEntity(url: string, key: string, entity: string, record: Row): Promise<Row> {
  const result = await crmCall(url, key, { action: "upsert", entity, record });
  return obj(result.record);
}

function dealFacts(deal: Row, property: Row, contact: Row): Row {
  return {
    deal_id: text(deal.id) || null,
    deal_title: text(deal.title) || null,
    stage: text(deal.stage) || null,
    assigned_to: text(deal.assigned_to) || null,
    seller_name: text(contact.name) || `${text(contact.first_name)} ${text(contact.last_name)}`.trim() || null,
    seller_phone: text(contact.phone) || null,
    seller_email: text(contact.email) || null,
    property_address: text(property.address) || null,
    city: text(property.city) || null,
    state: text(property.state) || null,
    zip: text(property.zip) || null,
    parcel_id: text(property.parcel_id) || null,
    asking_price: deal.asking_price ?? null,
    offer_price: deal.offer_price ?? null,
    arv: deal.arv ?? null,
    estimated_repairs: deal.estimated_repairs ?? null,
    motivation: text(deal.motivation) || null,
    timeline: text(deal.timeline) || null,
    notes: text(deal.notes) || null,
  };
}

async function prepareWork(
  url: string,
  key: string,
  task: Row,
  deal: Row,
  property: Row,
  contact: Row,
): Promise<Row> {
  const dealId = text(deal.id || links(task).deal_id || task.deal_id);
  const taskId = text(task.id);
  const workType = text(task.work_type);
  const facts = dealFacts(deal, property, contact);
  const baseExternal = `lifecycle-${taskId || `${dealId}-${workType}`}`;

  if (workType === "prepare_offer") {
    const offer = await upsertEntity(url, key, "offers", {
      source: "commandcore-deal-specialist-prep",
      external_id: `${baseExternal}-offer-draft`,
      amount: deal.offer_price ?? null,
      status: "draft_pending_owner_approval",
      terms: { facts, generated_terms: false },
      approval_required: true,
      external_action_started: false,
      links: { deal_id: dealId || null, task_id: taskId || null },
    });
    return { artifact_entity: "offers", artifact_id: text(offer.id), status: "draft_pending_owner_approval" };
  }

  if (workType === "prepare_contract") {
    const document = await upsertEntity(url, key, "documents", {
      source: "commandcore-deal-specialist-prep",
      external_id: `${baseExternal}-contract-prep`,
      name: "Contract preparation facts",
      document_type: "contract_prep_facts",
      status: "needs_approved_legal_template",
      facts,
      legal_terms_generated: false,
      approval_required: true,
      external_action_started: false,
      links: { deal_id: dealId || null, task_id: taskId || null },
    });
    return { artifact_entity: "documents", artifact_id: text(document.id), status: "needs_approved_legal_template" };
  }

  if (workType === "title_closing") {
    const document = await upsertEntity(url, key, "documents", {
      source: "commandcore-deal-specialist-prep",
      external_id: `${baseExternal}-closing-checklist`,
      name: "Title and closing readiness checklist",
      document_type: "title_closing_checklist",
      status: "internal_review_ready",
      facts,
      checklist: [
        "Confirm signed/executed contract is attached",
        "Confirm seller and property identity",
        "Confirm title/closing provider and contact",
        "Track title issues, payoff items, closing date, and required signatures",
      ],
      external_action_started: false,
      links: { deal_id: dealId || null, task_id: taskId || null },
    });
    return { artifact_entity: "documents", artifact_id: text(document.id), status: "internal_review_ready" };
  }

  const activityType = workType === "marketing_dispo" ? "marketing_dispo_prep_ready" : "deal_analysis_prep_ready";
  const title = workType === "marketing_dispo" ? "Marketing/disposition handoff facts ready" : "Deal analysis facts ready";
  const activity = await upsertEntity(url, key, "activities", {
    source: "commandcore-deal-specialist-prep",
    external_id: `${baseExternal}-prep`,
    activity_type: activityType,
    title,
    summary: title,
    occurred_at: new Date().toISOString(),
    details: { facts, external_action_started: false },
    links: { deal_id: dealId || null, task_id: taskId || null },
  });
  return { artifact_entity: "activities", artifact_id: text(activity.id), status: "internal_prep_ready" };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-deal-specialist-prep",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      owner_approval_required_for_offer: true,
      approved_legal_template_required_for_contract: true,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });
  let body: Row = {};
  try {
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const apply = body.apply !== false;
  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  try {
    const [tasks, deals, properties, contacts] = await Promise.all([
      listEntity(url, key, "tasks"),
      listEntity(url, key, "deals"),
      listEntity(url, key, "properties"),
      listEntity(url, key, "contacts"),
    ]);
    const dealById = new Map(deals.map((row) => [text(row.id), row]));
    const propertyById = new Map(properties.map((row) => [text(row.id), row]));
    const contactById = new Map(contacts.map((row) => [text(row.id), row]));
    const candidates = tasks.filter((task) =>
      text(task.task_type) === "deal_lifecycle_request" &&
      isOpen(task) &&
      text(task.prep_status) === "ready_for_specialist" &&
      text(task.specialist_prep_status) !== "prepared"
    );
    const results: Row[] = [];

    for (const task of candidates) {
      const dealId = text(links(task).deal_id || task.deal_id);
      const deal = dealById.get(dealId) || {};
      const dealLinks = links(deal);
      const property = propertyById.get(text(dealLinks.property_id)) || {};
      const contact = contactById.get(text(dealLinks.contact_id)) || {};

      if (!apply) {
        results.push({ task_id: text(task.id), deal_id: dealId, work_type: text(task.work_type), status: "would_prepare" });
        continue;
      }

      const artifact = await prepareWork(url, key, task, deal, property, contact);
      await upsertEntity(url, key, "tasks", {
        ...task,
        specialist_prep_status: "prepared",
        specialist_prep_artifact_entity: artifact.artifact_entity,
        specialist_prep_artifact_id: artifact.artifact_id,
        specialist_prep_result: artifact.status,
        specialist_prepared_at: new Date().toISOString(),
        external_action_started: false,
      });
      results.push({
        task_id: text(task.id),
        deal_id: dealId,
        work_type: text(task.work_type),
        status: "prepared",
        ...artifact,
      });
    }

    return jsonResponse(200, {
      ok: true,
      apply,
      candidate_count: candidates.length,
      prepared_count: results.filter((result) => result.status === "prepared").length,
      results,
      offer_approved: false,
      legal_terms_generated: false,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore deal specialist prep failed", error);
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "deal_specialist_prep_unavailable",
      external_action_started: false,
    });
  }
});
