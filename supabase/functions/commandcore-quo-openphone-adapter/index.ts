const SERVICE_VERSION = "2026-09-04.2";
const MAX_BODY_BYTES = 128 * 1024;
const MAX_EVENTS = 50;
const MAX_TEXT_LENGTH = 4000;
const SIGNATURE_TOLERANCE_MS = 5 * 60 * 1000;
const PROVIDERS = new Set(["quo", "openphone"]);

type JsonObject = Record<string, unknown>;

function jsonResponse(status: number, payload: JsonObject): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" },
  });
}
function text(value: unknown): string { return String(value ?? "").trim(); }
function lower(value: unknown): string { return text(value).toLowerCase(); }
function objectValue(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}
function first(...values: unknown[]): string {
  for (const value of values) {
    if (Array.isArray(value)) {
      for (const item of value) if (text(item)) return text(item);
    } else if (text(value)) return text(value);
  }
  return "";
}
function safeId(value: unknown): string {
  const candidate = text(value);
  return /^[A-Za-z0-9._:-]{1,200}$/.test(candidate) ? candidate : "";
}
function safePhone(value: unknown): string {
  const raw = first(value);
  const leadingPlus = raw.startsWith("+");
  const digits = raw.replace(/\D/g, "");
  if (digits.length < 7 || digits.length > 15) return "";
  return `${leadingPlus ? "+" : ""}${digits}`;
}
function safeText(value: unknown, maximum = MAX_TEXT_LENGTH): string {
  return text(value)
    .replace(/[\u0000-\u001F\u007F]/g, " ")
    .replace(/\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|webhook[_ -]?secret|password|private[_ -]?key|carrier[_ -]?pin)\s*[:=]\s*\S+/gi, "$1=[redacted]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [redacted]")
    .replace(/\s+/g, " ").slice(0, maximum);
}
function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a.charCodeAt(index) ^ b.charCodeAt(index);
  return difference === 0;
}
function decodeBase64(value: string): Uint8Array {
  try { return Uint8Array.from(atob(value), (character) => character.charCodeAt(0)); }
  catch { return new Uint8Array(); }
}
function encodeBase64(value: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(value)));
}
async function hmacSha256Base64(secret: Uint8Array, value: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return encodeBase64(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)));
}
function canonicalJson(raw: string): string {
  return JSON.stringify(JSON.parse(raw));
}
function inboundEnabled(): boolean {
  return lower(Deno.env.get("COMMANDCORE_QUO_OPENPHONE_MODE")) === "inbound";
}
async function validSignature(req: Request, raw: string, now = Date.now()): Promise<boolean> {
  const encodedSecret = Deno.env.get("COMMANDCORE_QUO_OPENPHONE_WEBHOOK_SECRET") ||
    Deno.env.get("COMMANDCORE_QUO_OPENPHONE_TEST_WEBHOOK_SECRET") || "";
  const signingKey = decodeBase64(encodedSecret);
  if (!signingKey.length) return false;
  const signatures = (req.headers.get("openphone-signature") || req.headers.get("x-openphone-signature") || "").split(",");
  for (const supplied of signatures) {
    const [scheme, version, timestampText, providedDigest] = supplied.trim().split(";");
    const timestamp = Number(timestampText);
    if (scheme !== "hmac" || version !== "1" || !Number.isFinite(timestamp) || Math.abs(now - timestamp) > SIGNATURE_TOLERANCE_MS || !providedDigest) continue;
    let digest: string;
    try { digest = await hmacSha256Base64(signingKey, `${timestampText}.${canonicalJson(raw)}`); }
    catch { return false; }
    if (constantTimeEqual(providedDigest, digest)) return true;
  }
  return false;
}
function providerName(body: JsonObject, data: JsonObject): string {
  const provider = lower(first(body.provider, data.provider, "openphone"));
  if (!PROVIDERS.has(provider)) throw new Error("unsupported_provider");
  return provider;
}
function eventData(body: JsonObject): JsonObject {
  const data = objectValue(body.data);
  return Object.keys(data).length ? objectValue(data.object || data) : objectValue(body.payload);
}
function inboundDirection(data: JsonObject): string {
  const supplied = lower(data.direction);
  if (supplied === "incoming" || supplied === "inbound") return "inbound";
  if (supplied === "outgoing" || supplied === "outbound") throw new Error("outbound_event_rejected");
  throw new Error("communication_direction_required");
}
function normalizedEventType(rawType: string, data: JsonObject): string {
  if (rawType === "message.received" || rawType === "sms.received") return "communication.sms.received";
  if (["call.missed", "call.no_answer"].includes(rawType)) return "communication.call.missed";
  if (["voicemail.received", "call.voicemail"].includes(rawType)) return "communication.voicemail.received";
  if (rawType === "call.completed") {
    if (Object.keys(objectValue(data.voicemail)).length) return "communication.voicemail.received";
    if (!text(data.answeredAt || data.answered_at)) return "communication.call.missed";
  }
  throw new Error("unsupported_event_type");
}
function eventSummary(eventType: string, data: JsonObject): string {
  const transcript = objectValue(data.transcript);
  const supplied = safeText(first(data.summary, transcript.summary, data.text, data.body), 1000);
  if (supplied) return supplied;
  if (eventType === "communication.call.missed") return "Missed inbound call";
  if (eventType === "communication.voicemail.received") return "Inbound voicemail received";
  throw new Error("message_body_required");
}
function normalizeEvent(body: JsonObject): JsonObject {
  const data = eventData(body);
  const rawType = lower(first(body.type, body.event_type, body.eventType, data.type, data.event_type));
  const direction = inboundDirection(data);
  const eventType = normalizedEventType(rawType, data);
  const provider = providerName(body, data);
  const eventId = safeId(first(body.id, body.event_id, body.eventId, data.event_id));
  const objectId = safeId(first(data.id, data.message_id, data.messageId, data.call_id, data.callId));
  const from = safePhone(first(data.from, data.from_number, data.fromNumber));
  const to = safePhone(first(data.to, data.to_number, data.toNumber));
  if (!eventId || !objectId) throw new Error("event_identity_required");
  if (!from || !to) throw new Error("phone_identity_required");
  const voicemail = objectValue(data.voicemail);
  const sourceConversationId = safeId(first(data.conversationId, data.conversation_id));
  return {
    event_id: `${provider}:${eventId}`,
    event_type: eventType,
    provider,
    provider_event_id: eventId,
    provider_object_id: objectId,
    occurred_at: safeText(first(data.createdAt, data.created_at, body.createdAt, body.created_at), 100),
    sender_identifier: from,
    recipient_identifier: to,
    contact_match: { phone: from },
    communication: {
      channel: eventType.includes(".sms.") ? "sms" : "phone",
      direction,
      from_phone: from,
      to_phone: to,
      status: eventType === "communication.call.missed" ? "missed" : "received",
      summary: eventSummary(eventType, data),
      source_conversation_id: sourceConversationId || null,
      voicemail_present: eventType === "communication.voicemail.received",
      voicemail_duration_seconds: Number(voicemail.duration || 0) || null,
    },
    source_attribution: { source: provider, medium: "phone", provider_account_label: safeText(data.account_label, 120) },
    source_adapter: "commandcore-quo-openphone-adapter",
    source_adapter_version: SERVICE_VERSION,
    estimated_cost: 0,
    actual_cost: 0,
    external_action_started: false,
  };
}
function requestEvents(body: JsonObject): JsonObject[] {
  const events = Array.isArray(body.events) ? body.events.map(objectValue) : [body];
  if (!events.length || events.length > MAX_EVENTS) throw new Error("invalid_event_count");
  return events;
}
async function captureInbound(event: JsonObject): Promise<JsonObject> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) throw new Error("commandcore_capture_not_configured");
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-inbound-communication-capture`, {
    method: "POST",
    headers: { authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({ communication_event: event }),
  });
  const result = await response.json().catch(() => ({})) as JsonObject;
  if (!response.ok || result.ok !== true || result.external_action_started === true) throw new Error("commandcore_capture_failed");
  return result;
}

Deno.serve(async (req) => {
  if (req.method === "GET") return jsonResponse(200, {
    ok: true, service: "commandcore-quo-openphone-adapter", version: SERVICE_VERSION,
    status: inboundEnabled() ? "inbound_only" : "activation_required",
    live_ingress_enabled: inboundEnabled(), supported_events: ["message.received", "call.completed"],
    canonical_destination: "commandcore-inbound-communication-capture",
    outbound_enabled: false, external_action_started: false,
  });
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed", external_action_started: false });
  if (!inboundEnabled()) return jsonResponse(403, { ok: false, error: "live_phone_ingress_disabled", external_action_started: false });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large", external_action_started: false });
  if (!(await validSignature(req, raw))) return jsonResponse(401, { ok: false, error: "invalid_signature", external_action_started: false });
  let body: JsonObject;
  try { body = JSON.parse(raw); }
  catch { return jsonResponse(400, { ok: false, error: "invalid_json", external_action_started: false }); }
  try {
    const normalizedEvents = requestEvents(body).map(normalizeEvent);
    const unique = new Map<string, JsonObject>();
    for (const event of normalizedEvents) unique.set(text(event.event_id), event);
    const captureResults: JsonObject[] = [];
    for (const event of unique.values()) captureResults.push(await captureInbound(event));
    return jsonResponse(202, {
      ok: true, accepted: captureResults.length,
      duplicates_ignored_in_request: normalizedEvents.length - unique.size,
      duplicate_retries_ignored: captureResults.filter((item) => item.duplicate_ignored === true).length,
      canonical_destination: "commandcore-inbound-communication-capture",
      communications_created: captureResults.filter((item) => item.communication_created === true).length,
      outbound_messages: 0, outbound_calls: 0,
      contact_mutations: 0, deal_mutations: 0, property_mutations: 0,
      external_action_started: false,
    });
  } catch (error) {
    const code = error instanceof Error ? error.message : "malformed_phone_event";
    const safeErrors = new Set([
      "unsupported_provider", "unsupported_event_type", "event_identity_required", "phone_identity_required",
      "invalid_event_count", "outbound_event_rejected", "communication_direction_required", "message_body_required",
    ]);
    return jsonResponse(safeErrors.has(code) ? 422 : 503, {
      ok: false, error: safeErrors.has(code) ? code : "inbound_capture_unavailable", external_action_started: false,
    });
  }
});
