const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 128 * 1024;

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

function lower(value: unknown): string {
  return text(value).toLowerCase();
}

function obj(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function suppliedToken(req: Request): string {
  const header = req.headers.get("x-commandcore-lead-token") || "";
  if (header) return header.trim();
  const authorization = req.headers.get("authorization") || "";
  return authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
}

function authed(req: Request): boolean {
  const supplied = suppliedToken(req);
  const inbound = Deno.env.get("COMMANDCORE_INBOUND_LEAD_TOKEN") || "";
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supplied) return false;
  if (inbound && constantTimeEqual(supplied, inbound)) return true;
  return Boolean(service && constantTimeEqual(supplied, service));
}

function cleanPhone(value: unknown): string {
  return text(value).replace(/[^0-9+]/g, "").slice(0, 24);
}

function cleanEmail(value: unknown): string {
  return lower(value).slice(0, 254);
}

function cleanAddressPart(value: unknown): string {
  return text(value).replace(/\s+/g, " ").slice(0, 180);
}

function hashKey(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return Math.abs(hash >>> 0).toString(36);
}

function leadIdentity(lead: Row): string {
  const source = lower(lead.source || lead.channel || "inbound");
  const external = lower(lead.external_id || lead.lead_id || lead.id);
  if (external) return `${source}:${external}`;
  const email = cleanEmail(lead.email || lead.contact_email);
  const phone = cleanPhone(lead.phone || lead.contact_phone);
  const address = lower(lead.property_address || lead.address);
  const name = lower(lead.name || `${text(lead.first_name)} ${text(lead.last_name)}`);
  return `${source}:${email}:${phone}:${address}:${name}`;
}

async function callCrm(url: string, key: string, entity: string, record: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify({ action: "upsert", entity, record }),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) {
    throw new Error(text(parsed.error) || `crm_${entity}_write_failed_${response.status}`);
  }
  return obj(parsed.record);
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-inbound-lead-capture",
      version: SERVICE_VERSION,
      status: "healthy",
      supported_lead_types: ["seller", "agent", "other"],
      duplicate_safe: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Row;
  try {
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const lead = obj(body.lead || body);
  const source = lower(lead.source || lead.channel || body.source || "inbound").slice(0, 80) || "inbound";
  const leadTypeRaw = lower(lead.lead_type || lead.type || "seller");
  const leadType = ["seller", "agent", "other"].includes(leadTypeRaw) ? leadTypeRaw : "other";
  const phone = cleanPhone(lead.phone || lead.contact_phone);
  const email = cleanEmail(lead.email || lead.contact_email);
  const firstName = text(lead.first_name).slice(0, 80);
  const lastName = text(lead.last_name).slice(0, 80);
  const fullName = text(lead.name) || `${firstName} ${lastName}`.trim();
  const address = cleanAddressPart(lead.property_address || lead.address);

  if (!phone && !email && !fullName) {
    return jsonResponse(422, { ok: false, error: "contact_identity_required" });
  }
  if (leadType === "seller" && !address && !text(lead.property_id)) {
    return jsonResponse(422, { ok: false, error: "seller_property_identity_required" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const identity = leadIdentity({ ...lead, source });
  const stable = hashKey(identity);
  const originalExternal = text(lead.external_id || lead.lead_id || lead.id);
  const baseExternal = originalExternal || `generated-${stable}`;

  try {
    const contact = await callCrm(supabaseUrl, serviceKey, "contacts", {
      source,
      external_id: `${baseExternal}-contact`,
      first_name: firstName || null,
      last_name: lastName || null,
      name: fullName || null,
      phone: phone || null,
      email: email || null,
      company: text(lead.company || lead.brokerage) || null,
      contact_type: leadType === "agent" ? "agent" : "seller",
      inbound_channel: text(lead.channel || source),
      notes: text(lead.notes || lead.message) || null,
      raw_lead_reference: originalExternal || null,
    });

    let property: Row = {};
    if (address || text(lead.property_id)) {
      property = await callCrm(supabaseUrl, serviceKey, "properties", {
        source,
        external_id: `${baseExternal}-property`,
        address: address || null,
        city: cleanAddressPart(lead.city) || null,
        state: text(lead.state).toUpperCase().slice(0, 2) || null,
        zip: text(lead.zip || lead.postal_code).slice(0, 12) || null,
        parcel_id: text(lead.parcel_id || lead.apn) || null,
        bedrooms: lead.bedrooms ?? null,
        bathrooms: lead.bathrooms ?? null,
        square_feet: lead.square_feet ?? lead.sqft ?? null,
        asking_price: lead.asking_price ?? null,
        links: { contact_id: text(contact.id) || null },
      });
    }

    const propertyLabel = address || text(lead.city) || "property not yet identified";
    const deal = await callCrm(supabaseUrl, serviceKey, "deals", {
      source,
      external_id: `${baseExternal}-deal`,
      title: text(lead.deal_title) || `${leadType === "agent" ? "Agent" : "Seller"} lead — ${propertyLabel}`,
      status: "Active",
      stage: "New Lead",
      lead_type: leadType,
      inbound_channel: text(lead.channel || source),
      assigned_to: text(lead.assigned_to) || null,
      asking_price: lead.asking_price ?? null,
      motivation: text(lead.motivation) || null,
      timeline: text(lead.timeline) || null,
      notes: text(lead.notes || lead.message) || null,
      links: {
        contact_id: text(contact.id) || null,
        property_id: text(property.id) || null,
      },
    });

    const activity = await callCrm(supabaseUrl, serviceKey, "activities", {
      source,
      external_id: `${baseExternal}-captured`,
      activity_type: "inbound_lead_captured",
      title: "Inbound lead captured",
      channel: text(lead.channel || source),
      occurred_at: text(lead.occurred_at || lead.created_at) || new Date().toISOString(),
      details: {
        lead_type: leadType,
        source,
        raw_lead_reference: originalExternal || null,
      },
      links: {
        deal_id: text(deal.id) || null,
        contact_id: text(contact.id) || null,
        property_id: text(property.id) || null,
      },
    });

    return jsonResponse(200, {
      ok: true,
      dedupe_key: stable,
      contact_id: text(contact.id) || null,
      property_id: text(property.id) || null,
      deal_id: text(deal.id) || null,
      activity_id: text(activity.id) || null,
      stage: "New Lead",
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore inbound lead capture failed", error);
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "lead_capture_failed",
      external_action_started: false,
    });
  }
});
