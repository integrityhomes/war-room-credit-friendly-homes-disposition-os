const SERVICE_VERSION = "2026-09-04.2";
const MAX_BODY_BYTES = 128 * 1024;
const MAX_MESSAGE_LENGTH = 10_000;
const CRM_SOURCE = "commandcore-inbound-communications";

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
function text(value: unknown): string { return String(value ?? "").trim(); }
function obj(value: unknown): Row { return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {}; }
function links(record: Row): Row { return obj(record.links); }
function recordId(record: Row): string { return text(record.id || record.external_id); }
function normalizePhone(value: unknown): string {
  const digits = text(value).replace(/\D/g, "");
  return digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
}
function normalizeEmail(value: unknown): string { return text(value).toLowerCase(); }
function safeIdentifier(value: unknown): string {
  const candidate = text(value);
  return /^[A-Za-z0-9._:@+-]{1,240}$/.test(candidate) ? candidate : "";
}
function safeText(value: unknown, maximum = MAX_MESSAGE_LENGTH): string {
  return text(value)
    .replace(/[\u0000-\u001F\u007F]/g, " ")
    .replace(/\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|webhook[_ -]?secret|password|private[_ -]?key|carrier[_ -]?pin)\s*[:=]\s*\S+/gi, "$1=[redacted]")
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [redacted]")
    .replace(/\s+/g, " ").slice(0, maximum);
}
function isActiveDeal(deal: Row): boolean {
  return !["closed", "cancelled", "canceled", "archived", "dead"].includes(text(deal.status || deal.stage).toLowerCase());
}
function isAuthenticated(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!expected || supplied.length !== expected.length) return false;
  let difference = 0;
  for (let index = 0; index < supplied.length; index += 1) difference |= supplied.charCodeAt(index) ^ expected.charCodeAt(index);
  return difference === 0;
}
async function crmRequest(url: string, key: string, action: string, entity: string, extra: Row = {}): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST", headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify({ action, entity, ...extra }),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(`crm_${entity}_${action}_failed`);
  return parsed;
}
async function listCrm(url: string, key: string, entity: string): Promise<Row[]> {
  const result = await crmRequest(url, key, "list", entity, { limit: 500 });
  return Array.isArray(result.records) ? result.records.map(obj) : [];
}
async function upsertCommunication(url: string, key: string, record: Row): Promise<Row> {
  return await crmRequest(url, key, "upsert", "communications", { record });
}
function contactCandidates(event: Row, contacts: Row[]): Row[] {
  const match = obj(event.contact_match);
  const explicitId = safeIdentifier(event.contact_id || match.contact_id);
  const externalReference = safeIdentifier(match.external_contact_reference || event.external_contact_reference);
  const phone = normalizePhone(match.phone || event.contact_phone || event.sender_identifier);
  const email = normalizeEmail(match.email || event.contact_email || event.sender_identifier);
  return contacts.filter((item) => {
    if (explicitId) return recordId(item) === explicitId;
    if (externalReference) {
      const references = obj(item.external_references);
      if (text(item.external_id) === externalReference || Object.values(references).some((value) => text(value) === externalReference)) return true;
    }
    return Boolean((phone && normalizePhone(item.phone) === phone) || (email && email.includes("@") && normalizeEmail(item.email) === email));
  });
}
function exactRecord(records: Row[], id: string): Row | null {
  const matches = records.filter((item) => recordId(item) === id);
  return matches.length === 1 ? matches[0] : null;
}
function matchContext(event: Row, contacts: Row[], properties: Row[], deals: Row[]): {
  contact: Row | null; property: Row | null; deal: Row | null; ambiguous: boolean;
} {
  const candidates = contactCandidates(event, contacts);
  if (candidates.length > 1) return { contact: null, property: null, deal: null, ambiguous: true };
  const contact = candidates.length === 1 ? candidates[0] : null;
  const eventLinks = obj(event.links);
  const explicitDealId = safeIdentifier(event.deal_id || eventLinks.deal_id);
  const explicitPropertyId = safeIdentifier(event.property_id || eventLinks.property_id);
  let deal = explicitDealId ? exactRecord(deals, explicitDealId) : null;
  if (explicitDealId && !deal) return { contact, property: null, deal: null, ambiguous: true };
  if (!deal && contact) {
    const contactId = recordId(contact);
    const related = deals.filter((item) => text(links(item).contact_id || item.contact_id) === contactId);
    const active = related.filter(isActiveDeal);
    const choices = active.length ? active : related;
    if (choices.length > 1) return { contact, property: null, deal: null, ambiguous: true };
    deal = choices.length === 1 ? choices[0] : null;
  }
  if (deal && contact) {
    const linkedContact = text(links(deal).contact_id || deal.contact_id);
    if (linkedContact && linkedContact !== recordId(contact)) return { contact: null, property: null, deal: null, ambiguous: true };
  }
  const linkedPropertyId = explicitPropertyId || text(links(deal || {}).property_id || deal?.property_id);
  const property = linkedPropertyId ? exactRecord(properties, linkedPropertyId) : null;
  if (linkedPropertyId && !property) return { contact, property: null, deal, ambiguous: true };
  return { contact, property, deal, ambiguous: false };
}
function isStopRequest(message: string): boolean {
  return /\b(stop|unsubscribe|opt[ -]?out|do not (?:text|call|contact|message))\b/i.test(message);
}

Deno.serve(async (req) => {
  if (req.method === "GET") return jsonResponse(200, {
    ok: true, service: "commandcore-inbound-communication-capture", version: SERVICE_VERSION,
    canonical_communications_store: true, communication_write_only: true, replay_safe: true,
    external_execution_enabled: false, external_action_started: false,
  });
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed", external_action_started: false });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized", external_action_started: false });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large", external_action_started: false });
  let body: Row;
  try { body = JSON.parse(raw || "{}") as Row; }
  catch { return jsonResponse(400, { ok: false, error: "invalid_json", external_action_started: false }); }
  const event = obj(body.communication_event || body);
  const communication = obj(event.communication);
  const attribution = obj(event.source_attribution);
  const source = safeIdentifier(event.provider || event.source || attribution.source);
  const externalMessageId = safeIdentifier(event.provider_object_id || event.external_message_id || event.event_id);
  const eventId = safeIdentifier(event.event_id || externalMessageId);
  const direction = text(communication.direction || event.direction).toLowerCase();
  const channel = safeText(communication.channel || event.channel, 40);
  const receivedAt = safeText(event.received_at || event.occurred_at, 100);
  const match = obj(event.contact_match);
  const senderIdentifier = safeIdentifier(event.sender_identifier || communication.from || communication.from_phone || match.email || match.phone);
  const recipientIdentifier = safeIdentifier(event.recipient_identifier || event.inbox || communication.to || communication.to_phone);
  const message = safeText(communication.message_text || communication.body || communication.summary || event.message_text || event.message);
  if (!source || !eventId || !externalMessageId) return jsonResponse(422, { ok: false, error: "communication_event_identity_required", external_action_started: false });
  if (direction !== "inbound") return jsonResponse(422, { ok: false, error: "inbound_only", external_action_started: false });
  if (!channel || !receivedAt || !senderIdentifier || !message) return jsonResponse(422, { ok: false, error: "inbound_communication_fields_required", external_action_started: false });
  if (event.external_action_started === true) return jsonResponse(422, { ok: false, error: "external_action_prohibited", external_action_started: false });
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured", external_action_started: false });
  try {
    const [contacts, properties, deals, communications] = await Promise.all([
      listCrm(supabaseUrl, serviceKey, "contacts"), listCrm(supabaseUrl, serviceKey, "properties"),
      listCrm(supabaseUrl, serviceKey, "deals"), listCrm(supabaseUrl, serviceKey, "communications"),
    ]);
    const matched = matchContext(event, contacts, properties, deals);
    const contactId = recordId(matched.contact || {});
    const dealId = recordId(matched.deal || {});
    const propertyId = recordId(matched.property || {});
    const assignedWorker = text(matched.deal?.assigned_to || matched.deal?.assigned_worker || matched.contact?.assigned_to || matched.contact?.assigned_worker);
    const deduplicationKey = `${source}:${externalMessageId}`.toLowerCase();
    const alreadyCaptured = communications.some((item) => text(item.source) === CRM_SOURCE && text(item.external_id).toLowerCase() === deduplicationKey);
    const stopRequested = isStopRequest(message);
    const result = await upsertCommunication(supabaseUrl, serviceKey, {
      source: CRM_SOURCE, external_id: deduplicationKey, communication_event_id: eventId,
      external_message_id: externalMessageId, provider: source, channel, direction: "inbound",
      received_at: receivedAt, occurred_at: receivedAt, sender_identifier: senderIdentifier,
      recipient_identifier: recipientIdentifier || null, inbox: recipientIdentifier || null,
      message_text: message, consent_stop_indicated: stopRequested,
      priority: stopRequested ? "immediate" : "unreviewed", ingestion_timestamp: new Date().toISOString(),
      source_adapter: safeText(event.source_adapter || source, 120),
      source_adapter_version: safeText(event.source_adapter_version || event.adapter_version || "unknown", 80),
      deduplication_key: deduplicationKey, source_attribution: attribution,
      match_status: matched.ambiguous ? "needs_human_review" : contactId ? "matched" : "unmatched",
      assigned_to: assignedWorker || null, estimated_cost: 0, actual_cost: 0,
      external_action_started: false,
      links: { contact_id: contactId || null, property_id: propertyId || null, deal_id: dealId || null },
    });
    const saved = obj(result.record);
    return jsonResponse(200, {
      ok: true, communication_id: recordId(saved) || null, duplicate_ignored: alreadyCaptured,
      communication_created: result.created === true,
      match_status: matched.ambiguous ? "needs_human_review" : contactId ? "matched" : "unmatched",
      contact_id: contactId || null, property_id: propertyId || null, deal_id: dealId || null,
      assigned_to: assignedWorker || null, consent_stop_indicated: stopRequested,
      consent_mutations: 0, contact_mutations: 0, deal_mutations: 0, property_mutations: 0,
      activities_created: 0, tasks_created: 0, outbound_messages: 0, outbound_calls: 0,
      external_action_started: false,
    });
  } catch {
    return jsonResponse(503, { ok: false, error: "communication_capture_unavailable", external_action_started: false });
  }
});
