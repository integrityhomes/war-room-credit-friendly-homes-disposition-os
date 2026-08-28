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
  const direct = req.headers.get("x-commandcore-lead-token") || "";
  if (direct) return direct.trim();
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

function first(...values: unknown[]): string {
  for (const value of values) {
    const candidate = text(value);
    if (candidate) return candidate;
  }
  return "";
}

function fieldData(value: unknown): Row {
  if (!Array.isArray(value)) return {};
  const result: Row = {};
  for (const item of value) {
    const row = obj(item);
    const key = lower(row.name).replace(/[^a-z0-9]+/g, "_");
    const values = Array.isArray(row.values) ? row.values : [];
    if (key && values.length) result[key] = text(values[0]);
  }
  return result;
}

function normalizeWebsite(raw: Row): Row {
  const contact = obj(raw.contact);
  const property = obj(raw.property);
  return {
    source: first(raw.source, "website"),
    channel: first(raw.channel, "website-form"),
    external_id: first(raw.external_id, raw.submission_id, raw.id),
    lead_type: first(raw.lead_type, "seller"),
    first_name: first(raw.first_name, contact.first_name),
    last_name: first(raw.last_name, contact.last_name),
    name: first(raw.name, contact.name),
    phone: first(raw.phone, contact.phone),
    email: first(raw.email, contact.email),
    property_address: first(raw.property_address, raw.address, property.address),
    city: first(raw.city, property.city),
    state: first(raw.state, property.state),
    zip: first(raw.zip, raw.postal_code, property.zip),
    asking_price: raw.asking_price ?? property.asking_price ?? null,
    motivation: first(raw.motivation, raw.reason_for_selling),
    timeline: first(raw.timeline, raw.selling_timeline),
    notes: first(raw.notes, raw.message, raw.comments),
    occurred_at: first(raw.occurred_at, raw.created_at, raw.submitted_at),
  };
}

function normalizeSms(raw: Row): Row {
  return {
    source: first(raw.source, "sms"),
    channel: first(raw.channel, "sms"),
    external_id: first(raw.external_id, raw.message_id, raw.id, raw.sid),
    lead_type: first(raw.lead_type, "seller"),
    name: first(raw.name, raw.contact_name, raw.from_name),
    phone: first(raw.phone, raw.from, raw.from_number, raw.contact_phone),
    email: first(raw.email, raw.contact_email),
    property_address: first(raw.property_address, raw.address),
    city: raw.city,
    state: raw.state,
    zip: first(raw.zip, raw.postal_code),
    notes: first(raw.message, raw.body, raw.text, raw.notes),
    occurred_at: first(raw.occurred_at, raw.created_at, raw.timestamp),
  };
}

function normalizeCall(raw: Row): Row {
  return {
    source: first(raw.source, "phone"),
    channel: first(raw.channel, "phone-call"),
    external_id: first(raw.external_id, raw.call_id, raw.id),
    lead_type: first(raw.lead_type, "seller"),
    name: first(raw.name, raw.contact_name, raw.caller_name),
    phone: first(raw.phone, raw.from, raw.from_number, raw.caller_number),
    email: first(raw.email, raw.contact_email),
    property_address: first(raw.property_address, raw.address),
    notes: first(raw.transcript, raw.summary, raw.notes),
    occurred_at: first(raw.occurred_at, raw.started_at, raw.created_at),
  };
}

function normalizeEmail(raw: Row): Row {
  return {
    source: first(raw.source, "email"),
    channel: first(raw.channel, "email"),
    external_id: first(raw.external_id, raw.message_id, raw.id),
    lead_type: first(raw.lead_type, raw.agent_email ? "agent" : "seller"),
    name: first(raw.name, raw.from_name, raw.contact_name),
    phone: first(raw.phone, raw.contact_phone),
    email: first(raw.email, raw.from_email, raw.reply_to, raw.agent_email),
    company: first(raw.company, raw.brokerage),
    property_address: first(raw.property_address, raw.address),
    notes: first(raw.body_text, raw.body, raw.snippet, raw.message, raw.notes),
    occurred_at: first(raw.occurred_at, raw.received_at, raw.created_at),
  };
}

function normalizeFacebook(raw: Row): Row {
  const fields = fieldData(raw.field_data);
  const names = first(fields.full_name, fields.name).split(/\s+/).filter(Boolean);
  return {
    source: first(raw.source, "facebook"),
    channel: first(raw.channel, "facebook-lead-form"),
    external_id: first(raw.external_id, raw.leadgen_id, raw.id),
    lead_type: first(raw.lead_type, "seller"),
    first_name: first(fields.first_name, names[0]),
    last_name: first(fields.last_name, names.slice(1).join(" ")),
    name: first(fields.full_name, fields.name),
    phone: first(fields.phone_number, fields.phone, raw.phone),
    email: first(fields.email, raw.email),
    property_address: first(fields.property_address, fields.address, raw.property_address),
    city: first(fields.city, raw.city),
    state: first(fields.state, raw.state),
    zip: first(fields.zip_code, fields.zip, raw.zip),
    asking_price: first(fields.asking_price, raw.asking_price) || null,
    motivation: first(fields.motivation, fields.reason_for_selling, raw.motivation),
    timeline: first(fields.timeline, fields.selling_timeline, raw.timeline),
    notes: first(fields.message, fields.comments, raw.message, raw.notes),
    occurred_at: first(raw.occurred_at, raw.created_time, raw.created_at),
  };
}

function normalizeAgent(raw: Row): Row {
  return {
    source: first(raw.source, "agent-referral"),
    channel: first(raw.channel, "agent"),
    external_id: first(raw.external_id, raw.lead_id, raw.id),
    lead_type: "agent",
    name: first(raw.name, raw.agent_name, raw.contact_name),
    phone: first(raw.phone, raw.agent_phone, raw.contact_phone),
    email: first(raw.email, raw.agent_email, raw.contact_email),
    company: first(raw.company, raw.brokerage),
    property_address: first(raw.property_address, raw.address),
    city: raw.city,
    state: raw.state,
    zip: first(raw.zip, raw.postal_code),
    asking_price: raw.asking_price ?? null,
    notes: first(raw.notes, raw.message),
    occurred_at: first(raw.occurred_at, raw.created_at),
  };
}

function normalize(provider: string, raw: Row): Row {
  if (["website", "website_form", "web_form", "landing_page"].includes(provider)) return normalizeWebsite(raw);
  if (["sms", "text", "text_message"].includes(provider)) return normalizeSms(raw);
  if (["call", "phone", "phone_call"].includes(provider)) return normalizeCall(raw);
  if (["email", "inbound_email"].includes(provider)) return normalizeEmail(raw);
  if (["facebook", "meta", "facebook_lead_form", "meta_lead_form"].includes(provider)) return normalizeFacebook(raw);
  if (["agent", "agent_referral", "mls_agent"].includes(provider)) return normalizeAgent(raw);
  return normalizeWebsite(raw);
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-lead-source-router",
      version: SERVICE_VERSION,
      status: "healthy",
      supported_sources: ["website", "sms", "phone_call", "email", "facebook_lead_form", "agent_referral", "generic"],
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const rawText = await req.text();
  if (new TextEncoder().encode(rawText).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Row;
  try {
    body = JSON.parse(rawText || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const provider = lower(body.provider || body.source_type || body.adapter || "generic");
  const raw = obj(body.payload || body.lead || body);
  const lead = normalize(provider, raw);
  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  try {
    const response = await fetch(`${url}/functions/v1/commandcore-inbound-lead-capture`, {
      method: "POST",
      headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
      body: JSON.stringify({ lead }),
    });
    const parsed = await response.json().catch(() => ({})) as Row;
    if (!response.ok || parsed.ok !== true) {
      return jsonResponse(response.status || 503, {
        ok: false,
        error: text(parsed.error) || `lead_capture_failed_${response.status}`,
        provider,
        external_action_started: false,
      });
    }
    return jsonResponse(200, {
      ok: true,
      provider,
      normalized_source: lead.source,
      normalized_channel: lead.channel,
      capture: parsed,
      external_action_started: false,
    });
  } catch (error) {
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "lead_router_failed",
      provider,
      external_action_started: false,
    });
  }
});
