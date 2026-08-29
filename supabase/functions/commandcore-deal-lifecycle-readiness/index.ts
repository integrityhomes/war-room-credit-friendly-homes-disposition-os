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

function present(value: unknown): boolean {
  return text(value).length > 0;
}

function requirements(workType: string, deal: Row, property: Row, contact: Row, documents: Row[]) {
  const signedDocument = documents.some((document) => {
    const status = text(document.status).toLowerCase();
    return status.includes("signed") || status.includes("executed");
  });
  const checks: Array<{ key: string; label: string; present: boolean }> = [];
  const add = (key: string, label: string, ok: boolean) => checks.push({ key, label, present: ok });

  add("property", "Property linked", Boolean(text(property.id) || text(property.address)));
  add("seller", "Seller/contact linked", Boolean(text(contact.id) || text(contact.name) || text(contact.phone) || text(contact.email)));

  if (workType === "deal_analysis" || workType === "prepare_offer") {
    add("asking_price", "Seller asking price or price expectation", present(deal.asking_price));
    add("arv", "ARV / value estimate", present(deal.arv));
    add("repairs", "Repair estimate or condition estimate", present(deal.estimated_repairs));
    add("motivation", "Seller motivation", present(deal.motivation) || present(deal.notes));
  }
  if (workType === "prepare_offer") {
    add("offer_price", "Proposed offer amount", present(deal.offer_price));
  }
  if (workType === "prepare_contract") {
    add("offer_price", "Approved/proposed purchase price", present(deal.offer_price));
    add("property_address", "Property address", present(property.address));
    add("seller_identity", "Seller identity", present(contact.name) || present(contact.first_name) || present(contact.last_name));
  }
  if (workType === "title_closing") {
    add("property_address", "Property address", present(property.address));
    add("seller_identity", "Seller identity", present(contact.name) || present(contact.first_name) || present(contact.last_name));
    add("contract_document", "Signed/executed contract document", signedDocument);
  }
  if (workType === "marketing_dispo") {
    add("property_address", "Property address", present(property.address));
    add("asking_or_sale_terms", "Marketing price / sale terms", present(deal.asking_price) || present(deal.offer_price));
  }

  const missing = checks.filter((check) => !check.present).map((check) => check.label);
  return { checks, missing, ready: missing.length === 0 };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-deal-lifecycle-readiness",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      legal_terms_generated: false,
      offer_decisions_generated: false,
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
    const [tasks, deals, properties, contacts, documents] = await Promise.all([
      listEntity(url, key, "tasks"),
      listEntity(url, key, "deals"),
      listEntity(url, key, "properties"),
      listEntity(url, key, "contacts"),
      listEntity(url, key, "documents"),
    ]);
    const dealById = new Map(deals.map((row) => [text(row.id), row]));
    const propertyById = new Map(properties.map((row) => [text(row.id), row]));
    const contactById = new Map(contacts.map((row) => [text(row.id), row]));
    const candidates = tasks.filter((task) => text(task.task_type) === "deal_lifecycle_request" && isOpen(task));
    const results: Row[] = [];

    for (const task of candidates) {
      const dealId = text(links(task).deal_id || task.deal_id);
      const deal = dealById.get(dealId) || {};
      const dealLinks = links(deal);
      const property = propertyById.get(text(dealLinks.property_id)) || {};
      const contact = contactById.get(text(dealLinks.contact_id)) || {};
      const dealDocuments = documents.filter((document) => text(links(document).deal_id || document.deal_id) === dealId);
      const workType = text(task.work_type);
      const readiness = requirements(workType, deal, property, contact, dealDocuments);
      const status = readiness.ready ? "ready_for_specialist" : "missing_information";

      if (apply) {
        const previousStatus = text(task.prep_status);
        await upsertEntity(url, key, "tasks", {
          ...task,
          prep_status: status,
          missing_information: readiness.missing,
          readiness_checks: readiness.checks,
          readiness_checked_at: new Date().toISOString(),
          external_action_started: false,
        });
        if (previousStatus !== status) {
          await upsertEntity(url, key, "activities", {
            source: "commandcore-deal-lifecycle-readiness",
            activity_type: "deal_lifecycle_readiness_checked",
            title: readiness.ready ? "Lifecycle work is ready" : "Lifecycle work needs information",
            summary: readiness.ready
              ? `${text(task.title) || workType} has the required deal facts.`
              : `${text(task.title) || workType} is missing: ${readiness.missing.join(", ")}`,
            occurred_at: new Date().toISOString(),
            details: {
              work_type: workType,
              prep_status: status,
              missing_information: readiness.missing,
              external_action_started: false,
            },
            links: { deal_id: dealId || null, task_id: text(task.id) || null },
          });
        }
      }

      results.push({
        task_id: text(task.id),
        deal_id: dealId,
        work_type: workType,
        prep_status: status,
        missing_information: readiness.missing,
      });
    }

    return jsonResponse(200, {
      ok: true,
      apply,
      candidate_count: candidates.length,
      ready_count: results.filter((result) => result.prep_status === "ready_for_specialist").length,
      missing_information_count: results.filter((result) => result.prep_status === "missing_information").length,
      results,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore deal lifecycle readiness failed", error);
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "deal_lifecycle_readiness_unavailable",
      external_action_started: false,
    });
  }
});
