const SERVICE_VERSION = "2026-09-04.1";
const MAX_BODY_BYTES = 128 * 1024;
const CRM_SOURCE = "commandcore-phone-communications";
const FOLLOW_UP_EVENTS = new Set([
  "communication.sms.received",
  "communication.call.missed",
  "communication.voicemail.received",
]);

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

function normalizePhone(value: unknown): string {
  const digits = text(value).replace(/\D/g, "");
  return digits.length === 11 && digits.startsWith("1") ? digits.slice(1) : digits;
}

function links(record: Row): Row {
  return obj(record.links);
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
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify({ action, entity, ...extra }),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `crm_${entity}_${action}_failed`);
  return parsed;
}

async function listCrm(url: string, key: string, entity: string): Promise<Row[]> {
  const result = await crmRequest(url, key, "list", entity, { limit: 500 });
  return Array.isArray(result.records) ? result.records.map(obj) : [];
}

async function upsertCrm(url: string, key: string, entity: string, record: Row): Promise<Row> {
  return obj((await crmRequest(url, key, "upsert", entity, { record })).record);
}

async function callService(url: string, key: string, service: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/${service}`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `${service}_failed`);
  return parsed;
}

async function matchExisting(url: string, key: string, phone: string): Promise<{ contact: Row | null; deal: Row | null; ambiguous: boolean }> {
  const contacts = (await listCrm(url, key, "contacts")).filter((item) => normalizePhone(item.phone) === phone);
  if (contacts.length !== 1) return { contact: null, deal: null, ambiguous: contacts.length > 1 };
  const contact = contacts[0];
  const contactId = text(contact.id);
  const deals = (await listCrm(url, key, "deals")).filter((item) => text(links(item).contact_id) === contactId);
  const activeDeals = deals.filter((item) => !["closed", "cancelled", "archived"].includes(text(item.status).toLowerCase()));
  const candidates = activeDeals.length ? activeDeals : deals;
  return { contact, deal: candidates.length === 1 ? candidates[0] : null, ambiguous: candidates.length > 1 };
}

async function safeIntake(url: string, key: string, event: Row): Promise<{ contact: Row | null; deal: Row | null }> {
  const eventType = text(event.event_type);
  const communication = obj(event.communication);
  const contactMatch = obj(event.contact_match);
  const attribution = obj(event.source_attribution);
  const phone = normalizePhone(contactMatch.phone);
  const intake = await callService(url, key, "commandcore-inbound-lead-capture", {
    source: text(event.provider) || "phone",
    external_id: `phone-contact-${phone}`,
    lead_type: "other",
    phone: text(contactMatch.phone),
    name: text(contactMatch.name),
    message: text(communication.summary),
    channel: text(communication.channel) || (eventType.includes("sms") ? "sms" : "phone-call"),
    campaign: text(attribution.campaign),
    occurred_at: text(event.occurred_at),
    external_action_started: false,
  });
  const contactId = text(intake.contact_id);
  const dealId = text(intake.deal_id);
  if (!contactId) return { contact: null, deal: null };
  const contacts = await listCrm(url, key, "contacts");
  const deals = dealId ? await listCrm(url, key, "deals") : [];
  return {
    contact: contacts.find((item) => text(item.id) === contactId) || null,
    deal: deals.find((item) => text(item.id) === dealId) || null,
  };
}

async function consentState(url: string, key: string, contactId: string): Promise<Row> {
  if (!contactId) return { available: false, suppressed: false, sms_eligible: false };
  try {
    const state = await callService(url, key, "commandcore-contact-ledger", { action: "evaluate_contact", contact_id: contactId });
    return { available: true, suppressed: state.suppressed === true, sms_eligible: state.sms_eligible === true };
  } catch {
    return { available: false, suppressed: false, sms_eligible: false };
  }
}

Deno.serve(async (req) => {
  if (req.method === "GET") return jsonResponse(200, {
    ok: true,
    service: "commandcore-inbound-communication-capture",
    version: SERVICE_VERSION,
    existing_contact_first: true,
    unmatched_safe_intake: true,
    replay_safe: true,
    external_execution_enabled: false,
    external_action_started: false,
  });
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed", external_action_started: false });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized", external_action_started: false });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large", external_action_started: false });
  let body: Row;
  try {
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json", external_action_started: false });
  }
  const event = obj(body.communication_event || body);
  const eventCommunication = obj(event.communication);
  const eventContactMatch = obj(event.contact_match);
  const eventAttribution = obj(event.source_attribution);
  const eventId = text(event.event_id);
  const eventType = text(event.event_type);
  const phone = normalizePhone(eventContactMatch.phone || event.contact_phone);
  if (!eventId || !eventType) return jsonResponse(422, { ok: false, error: "communication_event_identity_required", external_action_started: false });
  if (!phone) return jsonResponse(422, { ok: false, error: "contact_phone_required", external_action_started: false });
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured", external_action_started: false });

  try {
    let matched = await matchExisting(supabaseUrl, serviceKey, phone);
    let intakeUsed = false;
    if (!matched.contact && !matched.ambiguous && ["communication.sms.received", "communication.call.incoming", "communication.call.missed", "communication.voicemail.received"].includes(eventType)) {
      const intake = await safeIntake(supabaseUrl, serviceKey, event);
      matched = { ...matched, ...intake };
      intakeUsed = Boolean(intake.contact);
    }
    const contactId = text(matched.contact?.id);
    const dealId = text(matched.deal?.id);
    const propertyId = text(links(matched.deal || {}).property_id);
    const dealOwner = text(matched.deal?.assigned_to);
    const consent = await consentState(supabaseUrl, serviceKey, contactId);
    const commonLinks = { contact_id: contactId || null, property_id: propertyId || null, deal_id: dealId || null };
    const communication = await upsertCrm(supabaseUrl, serviceKey, "communications", {
      source: CRM_SOURCE,
      external_id: `phone-event-${eventId}`,
      provider: text(event.provider) || "Quo / OpenPhone",
      provider_account_reference: text(eventAttribution.provider_account_label) || null,
      channel: text(eventCommunication.channel),
      direction: text(eventCommunication.direction),
      status: text(eventCommunication.status),
      summary: text(eventCommunication.summary) || "Phone communication received",
      occurred_at: text(event.occurred_at) || new Date().toISOString(),
      recording_reference: text(eventCommunication.recording_reference) || null,
      transcript_reference: text(eventCommunication.transcript_reference) || null,
      source_attribution: eventAttribution,
      consent_state: consent.available ? (consent.suppressed ? "suppressed" : "reviewed") : "not_available",
      external_action_started: false,
      links: commonLinks,
    });
    const activity = await upsertCrm(supabaseUrl, serviceKey, "activities", {
      source: CRM_SOURCE,
      external_id: `phone-activity-${eventId}`,
      activity_type: "communication_event_received",
      title: text(event.display_name) || "Phone activity recorded",
      channel: text(eventCommunication.channel),
      occurred_at: text(event.occurred_at) || new Date().toISOString(),
      details: { event_type: eventType, status: text(eventCommunication.status), provider: text(event.provider), source_attribution: eventAttribution, intake_used: intakeUsed },
      external_action_started: false,
      links: { ...commonLinks, communication_id: text(communication.id) || null },
    });
    let followUp: Row = {};
    if (FOLLOW_UP_EVENTS.has(eventType) && dealId) {
      followUp = await upsertCrm(supabaseUrl, serviceKey, "tasks", {
        source: CRM_SOURCE,
        external_id: `phone-follow-up-${eventId}`,
        title: eventType === "communication.sms.received" ? "Review inbound text message" : "Follow up on phone activity",
        task_type: "crm_follow_up",
        work_type: "communication_follow_up",
        status: "open",
        assigned_to: dealOwner || null,
        note: consent.suppressed
          ? "Review the inbound communication. Contact is suppressed; do not send an outbound response without resolving the restriction."
          : "Review the inbound communication and choose the next permitted step.",
        consent_review_required: consent.available !== true || consent.suppressed === true,
        external_action_started: false,
        links: { ...commonLinks, communication_id: text(communication.id) || null },
      });
    }
    return jsonResponse(200, {
      ok: true,
      contact_id: contactId || null,
      property_id: propertyId || null,
      deal_id: dealId || null,
      communication_id: text(communication.id) || null,
      activity_id: text(activity.id) || null,
      follow_up_task_id: text(followUp.id) || null,
      existing_contact_matched: Boolean(contactId && !intakeUsed),
      existing_deal_matched: Boolean(dealId && !intakeUsed),
      unmatched_safe_intake_used: intakeUsed,
      ambiguous_match: matched.ambiguous,
      assigned_to: dealOwner || null,
      owner_preserved: Boolean(dealOwner),
      suppression_preserved: consent.suppressed === true,
      outbound_calls: 0,
      outbound_messages: 0,
      external_action_started: false,
    });
  } catch (error) {
    void error;
    return jsonResponse(503, { ok: false, error: "communication_capture_unavailable", external_action_started: false });
  }
});
