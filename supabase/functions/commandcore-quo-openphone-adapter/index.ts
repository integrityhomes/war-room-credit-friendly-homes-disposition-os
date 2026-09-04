const SERVICE_VERSION = "2026-09-04.1";
const MAX_BODY_BYTES = 128 * 1024;
const MAX_EVENTS = 50;
const MAX_TEXT_LENGTH = 4000;
const PROVIDERS = new Set(["quo", "openphone"]);

type JsonObject = Record<string, unknown>;

const EVENT_TYPES: Record<string, string> = {
  "message.received": "communication.sms.received",
  "sms.received": "communication.sms.received",
  "message.delivered": "communication.sms.delivery_updated",
  "message.failed": "communication.sms.delivery_updated",
  "message.undelivered": "communication.sms.delivery_updated",
  "sms.delivered": "communication.sms.delivery_updated",
  "sms.failed": "communication.sms.delivery_updated",
  "call.incoming": "communication.call.incoming",
  "call.ringing": "communication.call.incoming",
  "call.completed": "communication.call.completed",
  "call.ended": "communication.call.completed",
  "call.missed": "communication.call.missed",
  "call.no_answer": "communication.call.missed",
  "voicemail.received": "communication.voicemail.received",
  "call.voicemail": "communication.voicemail.received",
  "recording.ready": "communication.recording.ready",
  "call.recording.ready": "communication.recording.ready",
  "transcript.ready": "communication.transcript.ready",
  "summary.ready": "communication.transcript.ready",
  "call.transcript.ready": "communication.transcript.ready",
  "call.summary.ready": "communication.transcript.ready",
};

function jsonResponse(status: number, payload: JsonObject): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function lower(value: unknown): string {
  return text(value).toLowerCase();
}

function objectValue(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

function first(...values: unknown[]): string {
  for (const value of values) {
    const candidate = text(value);
    if (candidate) return candidate;
  }
  return "";
}

function safeId(value: unknown): string {
  const candidate = text(value);
  return /^[A-Za-z0-9._:-]{1,200}$/.test(candidate) ? candidate : "";
}

function safePhone(value: unknown): string {
  const raw = text(value);
  if (!raw) return "";
  const leadingPlus = raw.startsWith("+");
  const digits = raw.replace(/\D/g, "");
  if (digits.length < 7 || digits.length > 15) return "";
  return `${leadingPlus ? "+" : ""}${digits}`;
}

function safeText(value: unknown, maximum = MAX_TEXT_LENGTH): string {
  return text(value)
    .replace(/[\u0000-\u001F\u007F]/g, " ")
    .replace(/\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|webhook[_ -]?secret|password|carrier[_ -]?pin)\s*[:=]\s*\S+/gi, "$1=[redacted]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [redacted]")
    .replace(/\s+/g, " ")
    .slice(0, maximum);
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let index = 0; index < a.length; index++) difference |= a.charCodeAt(index) ^ b.charCodeAt(index);
  return difference === 0;
}

function hex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes)).map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function hmacSha256(secret: string, body: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body)));
}

async function validSignature(req: Request, raw: string): Promise<boolean> {
  const secret = Deno.env.get("COMMANDCORE_QUO_OPENPHONE_TEST_WEBHOOK_SECRET") || "";
  const supplied = first(req.headers.get("x-openphone-signature"), req.headers.get("x-quo-signature"));
  const signature = supplied.startsWith("sha256=") ? supplied.slice(7) : supplied;
  if (!secret || !signature || !/^[a-fA-F0-9]{64}$/.test(signature)) return false;
  return constantTimeEqual(signature.toLowerCase(), await hmacSha256(secret, raw));
}

function isTestMode(): boolean {
  return lower(Deno.env.get("COMMANDCORE_QUO_OPENPHONE_MODE") || "test") === "test";
}

function providerName(body: JsonObject, data: JsonObject): string {
  const provider = lower(first(body.provider, data.provider, "openphone"));
  if (!PROVIDERS.has(provider)) throw new Error("unsupported_provider");
  return provider;
}

function providerEventType(body: JsonObject, data: JsonObject): string {
  return lower(first(body.type, body.event_type, body.eventType, data.type, data.event_type));
}

function canonicalType(rawType: string): string {
  const result = EVENT_TYPES[rawType];
  if (!result) throw new Error("unsupported_event_type");
  return result;
}

function eventData(body: JsonObject): JsonObject {
  const data = objectValue(body.data);
  return Object.keys(data).length ? objectValue(data.object || data) : objectValue(body.payload);
}

function directionFor(eventType: string, data: JsonObject): string {
  const supplied = lower(data.direction);
  if (supplied === "inbound" || supplied === "outbound") return supplied;
  if (eventType === "communication.sms.delivery_updated") return "outbound";
  return "inbound";
}

function channelFor(eventType: string): string {
  return eventType.includes(".sms.") ? "sms" : "phone";
}

function followUpFor(eventType: string): JsonObject {
  if (eventType === "communication.sms.received") return { recommended: true, reason: "Reply to the inbound message" };
  if (eventType === "communication.call.missed") return { recommended: true, reason: "Return the missed call" };
  if (eventType === "communication.voicemail.received") return { recommended: true, reason: "Review the voicemail and follow up" };
  return { recommended: false, reason: "No automatic follow-up is required for this event" };
}

function statusFor(eventType: string, rawType: string, data: JsonObject): string {
  const supplied = lower(first(data.status, data.delivery_status));
  if (eventType === "communication.sms.delivery_updated") return supplied || (rawType.includes("fail") || rawType.includes("undelivered") ? "failed" : "delivered");
  if (eventType === "communication.call.missed") return "missed";
  if (eventType === "communication.call.completed") return "completed";
  if (eventType === "communication.call.incoming") return "incoming";
  return supplied || "received";
}

function normalizeEvent(body: JsonObject): JsonObject {
  const data = eventData(body);
  const rawType = providerEventType(body, data);
  const eventType = canonicalType(rawType);
  const provider = providerName(body, data);
  const eventId = safeId(first(body.id, body.event_id, body.eventId, data.event_id));
  const objectId = safeId(first(data.id, data.message_id, data.messageId, data.call_id, data.callId));
  if (!eventId || !objectId) throw new Error("event_identity_required");

  const from = safePhone(first(data.from, data.from_number, data.fromNumber));
  const to = safePhone(first(data.to, data.to_number, data.toNumber));
  if (!from || !to) throw new Error("phone_identity_required");
  const direction = directionFor(eventType, data);
  const matchPhone = direction === "inbound" ? from : to;
  const recording = objectValue(data.recording);
  const transcript = objectValue(data.transcript);
  const summary = safeText(first(data.summary, transcript.summary, data.text, data.body), 1000);

  return {
    event_id: `${provider}:${eventId}`,
    event_type: eventType,
    provider,
    provider_event_id: eventId,
    provider_object_id: objectId,
    occurred_at: safeText(first(data.occurred_at, data.created_at, data.createdAt, body.created_at), 100),
    contact_match: { phone: matchPhone },
    communication: {
      channel: channelFor(eventType),
      direction,
      from_phone: from,
      to_phone: to,
      status: statusFor(eventType, rawType, data),
      summary,
      recording_reference: safeId(first(data.recording_id, data.recordingId, recording.id)),
      transcript_reference: safeId(first(data.transcript_id, data.transcriptId, transcript.id)),
    },
    source_attribution: { source: provider, medium: "phone", provider_account_label: safeText(data.account_label, 120) },
    follow_up: followUpFor(eventType),
    test_mode: true,
    external_action_started: false,
  };
}

function requestEvents(body: JsonObject): JsonObject[] {
  const events = Array.isArray(body.events) ? body.events.map(objectValue) : [body];
  if (!events.length || events.length > MAX_EVENTS) throw new Error("invalid_event_count");
  return events;
}

Deno.serve(async (req) => {
  if (req.method === "GET") return jsonResponse(200, { ok: true, service: "commandcore-quo-openphone-adapter", version: SERVICE_VERSION, status: "test_mode_only", live_ingress_enabled: false, canonical_destination: "commandcore-inbound-communication-capture", external_action_started: false });
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed", external_action_started: false });
  if (!isTestMode()) return jsonResponse(403, { ok: false, error: "live_phone_ingress_disabled", external_action_started: false });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large", external_action_started: false });
  if (!(await validSignature(req, raw))) return jsonResponse(401, { ok: false, error: "invalid_signature", external_action_started: false });
  let body: JsonObject;
  try {
    body = JSON.parse(raw);
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json", external_action_started: false });
  }
  try {
    const normalizedEvents = requestEvents(body).map(normalizeEvent);
    const unique = new Map<string, JsonObject>();
    for (const event of normalizedEvents) unique.set(text(event.event_id), event);
    const canonicalEvents = Array.from(unique.values());
    return jsonResponse(202, {
      ok: true,
      accepted: unique.size,
      duplicates_ignored: normalizedEvents.length - unique.size,
      replay_safe: true,
      canonical_destination: "commandcore-inbound-communication-capture",
      communication_event: canonicalEvents.length === 1 ? canonicalEvents[0] : null,
      canonical_events: canonicalEvents,
      forwarding_started: false,
      external_action_started: false,
    });
  } catch (error) {
    const code = error instanceof Error ? error.message : "malformed_phone_event";
    const safeErrors = new Set(["unsupported_provider", "unsupported_event_type", "event_identity_required", "phone_identity_required", "invalid_event_count"]);
    return jsonResponse(422, { ok: false, error: safeErrors.has(code) ? code : "malformed_phone_event", external_action_started: false });
  }
});
