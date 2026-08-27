const SERVICE_VERSION = "2026-08-27.1";
const CONTACT_BUCKET = "commandcore-contact-registry";
const MAX_BODY_BYTES = 64 * 1024;
const CONSENT_CHANNELS = new Set(["sms", "email"]);
const CONSENT_STATES = new Set(["granted", "denied", "opt_out"]);

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function bearerToken(req: Request): string {
  const auth = req.headers.get("authorization") || "";
  return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function isAuthenticated(req: Request): boolean {
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = bearerToken(req);
  return Boolean(serviceRoleKey && supplied && constantTimeEqual(serviceRoleKey, supplied));
}

function normalized(value: unknown): string {
  return String(value ?? "").trim();
}

function normalizePhone(value: unknown): string {
  const digits = normalized(value).replace(/\D/g, "");
  if (digits.length === 10) return `1${digits}`;
  return digits;
}

function normalizeEmail(value: unknown): string {
  return normalized(value).toLowerCase();
}

function safeId(value: unknown): string {
  return normalized(value)
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function storageConfig() {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("storage_not_configured");
  return { supabaseUrl, serviceRoleKey };
}

function storageHeaders(serviceRoleKey: string): HeadersInit {
  return {
    authorization: `Bearer ${serviceRoleKey}`,
    apikey: serviceRoleKey,
    "content-type": "application/json",
  };
}

async function ensureBucket(): Promise<void> {
  const { supabaseUrl, serviceRoleKey } = storageConfig();
  const response = await fetch(`${supabaseUrl}/storage/v1/bucket/${CONTACT_BUCKET}`, {
    headers: storageHeaders(serviceRoleKey),
  });
  if (response.ok) return;
  if (response.status !== 404) throw new Error(`bucket_read_failed_${response.status}`);
  const created = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    method: "POST",
    headers: storageHeaders(serviceRoleKey),
    body: JSON.stringify({ id: CONTACT_BUCKET, name: CONTACT_BUCKET, public: false }),
  });
  if (!created.ok && created.status !== 409) throw new Error(`bucket_create_failed_${created.status}`);
}

async function readObject(path: string): Promise<Record<string, unknown> | null> {
  const { supabaseUrl, serviceRoleKey } = storageConfig();
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${CONTACT_BUCKET}/${path}`, {
    headers: storageHeaders(serviceRoleKey),
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`object_read_failed_${response.status}`);
  const parsed = await response.json();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  return parsed as Record<string, unknown>;
}

async function writeObject(path: string, payload: Record<string, unknown>, upsert = true): Promise<void> {
  const { supabaseUrl, serviceRoleKey } = storageConfig();
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${CONTACT_BUCKET}/${path}`, {
    method: "POST",
    headers: { ...storageHeaders(serviceRoleKey), "x-upsert": upsert ? "true" : "false" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`object_write_failed_${response.status}`);
}

async function resolveContactId(body: Record<string, unknown>): Promise<string> {
  const supplied = safeId(body.contact_id);
  if (supplied) return supplied;
  const phone = normalizePhone(body.phone);
  const email = normalizeEmail(body.email);
  if (!phone && !email) return "";
  return `c_${(await sha256(`${phone}|${email}`)).slice(0, 32)}`;
}

function consentSnapshot(contact: Record<string, unknown>, channel: string) {
  const consent = contact.consent && typeof contact.consent === "object" && !Array.isArray(contact.consent)
    ? contact.consent as Record<string, unknown>
    : {};
  const value = consent[channel];
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

async function upsertContact(body: Record<string, unknown>) {
  const contactId = await resolveContactId(body);
  if (!contactId) return jsonResponse(422, { ok: false, error: "contact_identity_required" });
  const path = `contacts/${contactId}.json`;
  const current = await readObject(path) || {};
  const now = new Date().toISOString();
  const phone = normalizePhone(body.phone) || normalized(current.phone);
  const email = normalizeEmail(body.email) || normalized(current.email);
  const record: Record<string, unknown> = {
    ...current,
    contact_id: contactId,
    first_name: normalized(body.first_name) || normalized(current.first_name),
    last_name: normalized(body.last_name) || normalized(current.last_name),
    phone,
    email,
    source: normalized(body.source) || normalized(current.source) || "unknown",
    status: normalized(body.status) || normalized(current.status) || "active",
    tags: Array.isArray(body.tags) ? body.tags.map(normalized).filter(Boolean) : current.tags || [],
    market_preferences: Array.isArray(body.market_preferences)
      ? body.market_preferences.map(normalized).filter(Boolean)
      : current.market_preferences || [],
    consent: current.consent || {},
    created_at: normalized(current.created_at) || now,
    updated_at: now,
  };
  await writeObject(path, record);
  if (phone) await writeObject(`indexes/phone/${await sha256(phone)}.json`, { contact_id: contactId });
  if (email) await writeObject(`indexes/email/${await sha256(email)}.json`, { contact_id: contactId });
  return jsonResponse(200, { ok: true, action: "upsert_contact", contact_id: contactId, stored: true });
}

async function recordConsent(body: Record<string, unknown>) {
  const contactId = safeId(body.contact_id);
  const channel = normalized(body.channel).toLowerCase();
  const state = normalized(body.state).toLowerCase();
  if (!contactId) return jsonResponse(422, { ok: false, error: "contact_id_required" });
  if (!CONSENT_CHANNELS.has(channel)) return jsonResponse(422, { ok: false, error: "invalid_consent_channel" });
  if (!CONSENT_STATES.has(state)) return jsonResponse(422, { ok: false, error: "invalid_consent_state" });
  const contactPath = `contacts/${contactId}.json`;
  const contact = await readObject(contactPath);
  if (!contact) return jsonResponse(404, { ok: false, error: "contact_not_found" });
  const now = new Date().toISOString();
  const eventId = crypto.randomUUID();
  const event = {
    event_id: eventId,
    contact_id: contactId,
    channel,
    state,
    source: normalized(body.source) || "unknown",
    evidence_reference: normalized(body.evidence_reference),
    recorded_by: normalized(body.recorded_by) || "system",
    recorded_at: now,
  };
  await writeObject(`consent-ledger/${contactId}/${now.replace(/[:.]/g, "-")}-${eventId}.json`, event, false);
  const consent = contact.consent && typeof contact.consent === "object" && !Array.isArray(contact.consent)
    ? { ...(contact.consent as Record<string, unknown>) }
    : {};
  consent[channel] = {
    state,
    source: event.source,
    evidence_reference: event.evidence_reference,
    recorded_at: now,
    event_id: eventId,
  };
  await writeObject(contactPath, { ...contact, consent, updated_at: now });
  return jsonResponse(200, { ok: true, action: "record_consent", contact_id: contactId, channel, state, event_id: eventId });
}

async function evaluateContact(body: Record<string, unknown>) {
  const contactId = safeId(body.contact_id);
  if (!contactId) return jsonResponse(422, { ok: false, error: "contact_id_required" });
  const contact = await readObject(`contacts/${contactId}.json`);
  if (!contact) return jsonResponse(404, { ok: false, error: "contact_not_found" });
  const status = normalized(contact.status).toLowerCase();
  const smsState = normalized(consentSnapshot(contact, "sms").state).toLowerCase();
  const emailState = normalized(consentSnapshot(contact, "email").state).toLowerCase();
  const active = status !== "suppressed" && status !== "inactive";
  const smsEligible = active && Boolean(normalizePhone(contact.phone)) && smsState === "granted";
  const emailEligible = active && Boolean(normalizeEmail(contact.email)) && emailState === "granted";
  return jsonResponse(200, {
    ok: true,
    action: "evaluate_contact",
    contact_id: contactId,
    active,
    sms_eligible: smsEligible,
    email_eligible: emailEligible,
    sms_consent_state: smsState || "unknown",
    email_consent_state: emailState || "unknown",
    suppressed: !active || smsState === "opt_out" || emailState === "opt_out",
  });
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-contact-ledger",
      version: SERVICE_VERSION,
      status: "healthy",
      storage: "private_supabase_storage",
      external_delivery_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }
  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }
  try {
    await ensureBucket();
    const action = normalized(body.action).toLowerCase();
    if (action === "upsert_contact") return await upsertContact(body);
    if (action === "record_consent") return await recordConsent(body);
    if (action === "evaluate_contact") return await evaluateContact(body);
    return jsonResponse(422, { ok: false, error: "unsupported_action" });
  } catch (error) {
    console.error("CommandCore contact ledger failed", error);
    return jsonResponse(503, { ok: false, error: "contact_ledger_unavailable" });
  }
});
