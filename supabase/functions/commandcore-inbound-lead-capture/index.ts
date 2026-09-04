const SERVICE_VERSION = "2026-09-04.1";
const MAX_BODY_BYTES = 128 * 1024;
const CANONICAL_SOURCE = "commandcore-canonical-intake";
const SUPPORTED_LEAD_TYPES = new Set(["seller", "buyer", "owner_finance_buyer", "investor_buyer_interest", "agent", "other"]);

type Row = Record<string, unknown>;
type AuthMode = "none" | "inbound_token" | "service_role";

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

function authenticate(req: Request): AuthMode {
  const supplied = suppliedToken(req);
  const inbound = Deno.env.get("COMMANDCORE_INBOUND_LEAD_TOKEN") || "";
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supplied) return "none";
  if (service && constantTimeEqual(supplied, service)) return "service_role";
  if (inbound && constantTimeEqual(supplied, inbound)) return "inbound_token";
  return "none";
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

function safeSegment(value: unknown): string {
  return text(value).replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "record";
}

function deterministicCrmId(entity: string, externalId: string): string {
  const input = `${entity}:${CANONICAL_SOURCE}:${externalId.toLowerCase()}`;
  return `imp-${hashKey(input)}-${safeSegment(externalId).slice(0, 72)}`;
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

async function getCrm(url: string, key: string, entity: string, id: string): Promise<Row | null> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify({ action: "get", entity, id }),
  });
  if (response.status === 404) return null;
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `crm_${entity}_read_failed_${response.status}`);
  return obj(parsed.record);
}

async function callService(url: string, key: string, service: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/${service}`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `${service}_failed_${response.status}`);
  return parsed;
}

function leadType(value: unknown): string {
  const candidate = lower(value || "seller");
  return SUPPORTED_LEAD_TYPES.has(candidate) ? candidate : "other";
}

function isBuyerLead(value: string): boolean {
  return ["buyer", "owner_finance_buyer", "investor_buyer_interest"].includes(value);
}

function identityPart(value: unknown): string {
  return lower(value).replace(/[^a-z0-9]+/g, "");
}

function sourceAttribution(existing: Row | null, event: Row, lead: Row, source: string, eventId: string): Row {
  const prior = obj(existing?.source_attribution);
  const campaign = text(event.campaign || lead.campaign);
  const medium = text(event.medium || lead.medium);
  const sourceDetail = text(event.source_detail || lead.source_detail);
  return {
    first_source: text(prior.first_source || prior.source) || source,
    first_campaign: text(prior.first_campaign || prior.campaign) || campaign || null,
    latest_source: source,
    latest_campaign: campaign || null,
    medium: medium || text(prior.medium) || null,
    source_detail: sourceDetail || text(prior.source_detail) || null,
    source_event_id: eventId || null,
    meta_page_id: text(lead.meta_page_id) || text(prior.meta_page_id) || null,
    meta_form_id: text(lead.meta_form_id) || text(prior.meta_form_id) || null,
    meta_leadgen_id: text(lead.meta_leadgen_id) || text(prior.meta_leadgen_id) || null,
    meta_campaign_id: text(lead.meta_campaign_id) || text(prior.meta_campaign_id) || null,
    meta_adset_id: text(lead.meta_adset_id) || text(prior.meta_adset_id) || null,
    meta_ad_id: text(lead.meta_ad_id) || text(prior.meta_ad_id) || null,
  };
}

async function preserveConsent(url: string, key: string, contactId: string, lead: Row, source: string): Promise<Row[]> {
  const results: Row[] = [];
  for (const channel of ["sms", "email"]) {
    const state = lower(lead[`${channel}_consent_state`]);
    if (!state) continue;
    const evidence = text(lead[`${channel}_consent_evidence`] || lead.consent_evidence_reference);
    if (state === "granted" && !evidence) throw new Error("granted_consent_requires_evidence");
    results.push(await callService(url, key, "commandcore-contact-ledger", {
      action: "record_consent", contact_id: contactId, channel, state, source,
      evidence_reference: evidence || null, recorded_by: "commandcore-inbound-lead-capture",
    }));
  }
  return results;
}

async function preserveBuyerPreferences(url: string, key: string, contactId: string, lead: Row): Promise<Row | null> {
  if (!isBuyerLead(leadType(lead.lead_type))) return null;
  return await callService(url, key, "commandcore-buyer-profile", {
    action: "update_preferences", contact_id: contactId,
    market_preferences: lead.market_preferences, property_types: lead.property_types,
    max_purchase_price: lead.max_purchase_price, max_monthly_payment: lead.max_monthly_payment,
    min_down_payment: lead.min_down_payment, max_down_payment: lead.max_down_payment,
    min_bedrooms: lead.min_bedrooms, min_bathrooms: lead.min_bathrooms,
    financing_preferences: lead.financing_preferences, condition_preferences: lead.condition_preferences,
    notes: lead.notes,
  });
}

async function routeLead(
  url: string,
  key: string,
  stable: string,
  source: string,
  propertyId: string,
): Promise<Row> {
  try {
    const response = await fetch(`${url}/functions/v1/commandcore-owner-routing`, {
      method: "POST",
      headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
      body: JSON.stringify({
        items: [{
          action_id: `inbound-lead-${stable}`,
          property_id: propertyId || null,
          channel_key: source,
          readiness: "manual",
          reasons: ["new_lead"],
          required_actions: ["work new lead"],
        }],
      }),
    });
    const parsed = await response.json().catch(() => ({})) as Row;
    if (!response.ok || parsed.ok !== true) {
      return { status: "unassigned", reason: text(parsed.error) || `routing_failed_${response.status}` };
    }
    const assignments = Array.isArray(parsed.assignments) ? parsed.assignments : [];
    const assignment = assignments.length ? obj(assignments[0]) : {};
    if (!text(assignment.owner_id) && !text(assignment.owner_name)) {
      return { status: "unassigned", reason: "no_available_owner" };
    }
    return {
      status: "assigned",
      owner_id: text(assignment.owner_id) || null,
      owner_name: text(assignment.owner_name) || null,
      routing_reason: text(assignment.routing_reason) || null,
      capacity_score: assignment.capacity_score ?? null,
    };
  } catch (error) {
    console.error("CommandCore inbound lead routing failed", error);
    return { status: "unassigned", reason: "routing_service_unavailable" };
  }
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-inbound-lead-capture",
      version: SERVICE_VERSION,
      status: "healthy",
      supported_lead_types: [...SUPPORTED_LEAD_TYPES],
      legacy_lead_types_retained: ["seller", "agent", "other"],
      duplicate_safe: true,
      canonical_integration_event: true,
      consent_preservation: true,
      buyer_preference_preservation: true,
      follow_up_creation: true,
      automatic_owner_routing: true,
      external_assignment_override_allowed: false,
      internal_assignment_override_requires_service_role: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  const callerAuth = authenticate(req);
  if (callerAuth === "none") return jsonResponse(401, { ok: false, error: "unauthorized" });

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

  const integrationEvent = obj(body.integration_event);
  const canonicalEventType = text(integrationEvent.event_type);
  const canonicalLeadEvent = Object.keys(integrationEvent).length > 0 && ["website.lead_submitted", "meta.lead_submitted"].includes(canonicalEventType);
  const lead = obj(integrationEvent.lead || body.lead || body);
  const source = lower(integrationEvent.source || lead.source || lead.channel || body.source || "inbound").slice(0, 80) || "inbound";
  const normalizedLeadType = leadType(lead.lead_type || lead.type || "seller");
  const phone = cleanPhone(lead.phone || lead.contact_phone);
  const email = cleanEmail(lead.email || lead.contact_email);
  const firstName = text(lead.first_name).slice(0, 80);
  const lastName = text(lead.last_name).slice(0, 80);
  const fullName = text(lead.name) || `${firstName} ${lastName}`.trim();
  const address = cleanAddressPart(lead.property_address || lead.address);

  if (!phone && !email && !fullName) {
    return jsonResponse(422, { ok: false, error: "contact_identity_required" });
  }
  if (normalizedLeadType === "seller" && !address && !text(lead.source_property_id || lead.property_id)) {
    return jsonResponse(422, { ok: false, error: "seller_property_identity_required" });
  }
  if (canonicalLeadEvent) {
    const sharedEvidence = text(lead.consent_evidence_reference);
    const smsEvidence = text(lead.sms_consent_evidence) || sharedEvidence;
    const emailEvidence = text(lead.email_consent_evidence) || sharedEvidence;
    if ((lower(lead.sms_consent_state) === "granted" && !smsEvidence) || (lower(lead.email_consent_state) === "granted" && !emailEvidence)) {
      return jsonResponse(422, { ok: false, error: "granted_consent_requires_evidence" });
    }
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const originalExternal = text(integrationEvent.event_id || lead.source_event_id || lead.external_id || lead.lead_id || lead.id);
  const eventStable = hashKey(originalExternal ? `${source}:${originalExternal}` : leadIdentity({ ...lead, source }));
  const legacyBaseExternal = originalExternal || `generated-${eventStable}`;
  const contactIdentity = cleanEmail(lead.email || lead.contact_email) || cleanPhone(lead.phone || lead.contact_phone)
    || `${identityPart(lead.name || `${text(lead.first_name)} ${text(lead.last_name)}`)}:${identityPart(address)}`;
  const contactStable = hashKey(contactIdentity);
  const propertyParts = [address, cleanAddressPart(lead.city), text(lead.state).toUpperCase(), text(lead.zip || lead.postal_code)].map(identityPart);
  const propertyIdentity = text(lead.source_property_id || lead.property_id)
    || (propertyParts.some(Boolean) ? propertyParts.join(":") : "");
  const propertyStable = propertyIdentity ? hashKey(propertyIdentity) : "";
  const dealStable = hashKey(`${normalizedLeadType}:${contactStable}:${propertyStable || "no-property"}`);
  const recordSource = canonicalLeadEvent ? CANONICAL_SOURCE : source;
  const contactExternal = canonicalLeadEvent ? `canonical-contact-${contactStable}` : `${legacyBaseExternal}-contact`;
  const propertyExternal = propertyStable ? canonicalLeadEvent ? `canonical-property-${propertyStable}` : `${legacyBaseExternal}-property` : "";
  const dealExternal = canonicalLeadEvent ? `canonical-deal-${dealStable}` : `${legacyBaseExternal}-deal`;
  let existingContact: Row | null = null;
  let existingProperty: Row | null = null;
  let existingDeal: Row | null = null;
  let existingFollowUp: Row | null = null;

  try {
    if (canonicalLeadEvent) {
      existingContact = await getCrm(supabaseUrl, serviceKey, "contacts", deterministicCrmId("contacts", contactExternal));
      existingProperty = propertyExternal
        ? await getCrm(supabaseUrl, serviceKey, "properties", deterministicCrmId("properties", propertyExternal))
        : null;
      existingDeal = await getCrm(supabaseUrl, serviceKey, "deals", deterministicCrmId("deals", dealExternal));
      existingFollowUp = await getCrm(supabaseUrl, serviceKey, "tasks", deterministicCrmId("tasks", `canonical-follow-up-${dealStable}`));
    }
    const contactAttribution = sourceAttribution(existingContact, integrationEvent, lead, source, originalExternal);
    const propertyAttribution = sourceAttribution(existingProperty, integrationEvent, lead, source, originalExternal);
    const dealAttribution = sourceAttribution(existingDeal, integrationEvent, lead, source, originalExternal);
    const contact = await callCrm(supabaseUrl, serviceKey, "contacts", {
      source: recordSource,
      external_id: contactExternal,
      first_name: firstName || existingContact?.first_name || null,
      last_name: lastName || existingContact?.last_name || null,
      name: fullName || existingContact?.name || null,
      phone: phone || existingContact?.phone || null,
      email: email || existingContact?.email || null,
      company: text(lead.company || lead.brokerage) || existingContact?.company || null,
      contact_type: normalizedLeadType === "agent" ? "agent" : isBuyerLead(normalizedLeadType) ? "buyer" : "seller",
      lead_type: normalizedLeadType,
      source_attribution: contactAttribution,
      inbound_channel: text(lead.channel || source),
      notes: text(lead.notes || lead.message) || null,
      raw_lead_reference: originalExternal || null,
    });

    let property: Row = {};
    if (propertyStable) {
      property = await callCrm(supabaseUrl, serviceKey, "properties", {
        source: recordSource,
        external_id: propertyExternal,
        address: address || existingProperty?.address || null,
        city: cleanAddressPart(lead.city) || existingProperty?.city || null,
        state: text(lead.state).toUpperCase().slice(0, 2) || existingProperty?.state || null,
        zip: text(lead.zip || lead.postal_code).slice(0, 12) || existingProperty?.zip || null,
        parcel_id: text(lead.parcel_id || lead.apn) || existingProperty?.parcel_id || null,
        bedrooms: lead.bedrooms ?? existingProperty?.bedrooms ?? null,
        bathrooms: lead.bathrooms ?? existingProperty?.bathrooms ?? null,
        square_feet: lead.square_feet ?? lead.sqft ?? existingProperty?.square_feet ?? null,
        asking_price: lead.asking_price ?? existingProperty?.asking_price ?? null,
        source_attribution: propertyAttribution,
        links: { contact_id: text(contact.id) || null },
      });
    }

    const requestedOwner = text(lead.assigned_to);
    const explicitOwner = callerAuth === "service_role" ? requestedOwner : "";
    const assignmentOverrideIgnored = Boolean(requestedOwner && callerAuth !== "service_role");
    const existingOwner = text(existingDeal?.assigned_to);
    const routing = existingOwner
      ? { status: "preserved", owner_name: existingOwner }
      : explicitOwner
      ? { status: "explicit", owner_name: explicitOwner }
      : await routeLead(supabaseUrl, serviceKey, dealStable, source, text(property.id));
    const assignedTo = existingOwner || explicitOwner || text(routing.owner_name) || text(routing.owner_id) || null;

    const propertyLabel = address || text(lead.city) || "property not yet identified";
    const deal = await callCrm(supabaseUrl, serviceKey, "deals", {
      source: recordSource,
      external_id: dealExternal,
      title: text(lead.deal_title) || text(existingDeal?.title) || `${normalizedLeadType.replaceAll("_", " ")} lead — ${propertyLabel}`,
      status: text(existingDeal?.status) || "Active",
      stage: text(existingDeal?.stage) || "New Lead",
      lead_type: normalizedLeadType,
      inbound_channel: text(lead.channel || source),
      assigned_to: assignedTo,
      assignment_status: text(routing.status) || (assignedTo ? "assigned" : "unassigned"),
      assignment_owner_id: text(routing.owner_id) || null,
      assignment_reason: text(routing.routing_reason || routing.reason) || null,
      asking_price: lead.asking_price ?? null,
      motivation: text(lead.motivation) || null,
      timeline: text(lead.timeline) || null,
      notes: text(lead.notes || lead.message) || null,
      source_attribution: { ...dealAttribution, channel: text(integrationEvent.channel || lead.channel || source) },
      links: {
        contact_id: text(contact.id) || null,
        property_id: text(property.id) || null,
      },
    });

    const consentResults = canonicalLeadEvent
      ? await preserveConsent(supabaseUrl, serviceKey, text(contact.id), lead, source)
      : [];
    const preferences = canonicalLeadEvent
      ? await preserveBuyerPreferences(supabaseUrl, serviceKey, text(contact.id), lead)
      : null;

    const activity = await callCrm(supabaseUrl, serviceKey, "activities", {
      source: recordSource,
      external_id: canonicalLeadEvent ? `canonical-intake-${dealStable}` : `${legacyBaseExternal}-captured`,
      activity_type: "inbound_lead_captured",
      title: "Inbound lead captured",
      channel: text(lead.channel || source),
      occurred_at: text(lead.occurred_at || lead.created_at) || new Date().toISOString(),
      details: {
        lead_type: normalizedLeadType,
        source,
        campaign: text(integrationEvent.campaign || lead.campaign) || null,
        medium: text(integrationEvent.medium || lead.medium) || null,
        source_detail: text(integrationEvent.source_detail || lead.source_detail) || null,
        meta_page_id: text(lead.meta_page_id) || null,
        meta_form_id: text(lead.meta_form_id) || null,
        meta_campaign_id: text(lead.meta_campaign_id) || null,
        meta_adset_id: text(lead.meta_adset_id) || null,
        meta_ad_id: text(lead.meta_ad_id) || null,
        raw_lead_reference: originalExternal || null,
        assignment_status: text(routing.status) || null,
        assigned_to: assignedTo,
        assignment_reason: text(routing.routing_reason || routing.reason) || null,
        assignment_override_ignored: assignmentOverrideIgnored,
      },
      links: {
        deal_id: text(deal.id) || null,
        contact_id: text(contact.id) || null,
        property_id: text(property.id) || null,
      },
    });

    const followUp = canonicalLeadEvent ? await callCrm(supabaseUrl, serviceKey, "tasks", {
      source: recordSource,
      external_id: `canonical-follow-up-${dealStable}`,
      title: canonicalEventType === "meta.lead_submitted" ? "Follow up with Meta lead" : "Follow up with website lead",
      task_type: "crm_follow_up",
      work_type: "lead_follow_up",
      status: text(existingFollowUp?.status) || "open",
      assigned_to: assignedTo,
      note: text(lead.notes || lead.message) || (canonicalEventType === "meta.lead_submitted" ? "Review the new Meta lead and choose the next contact step." : "Review the new website lead and choose the next contact step."),
      source_attribution: dealAttribution,
      external_action_started: false,
      links: { deal_id: text(deal.id) || null, contact_id: text(contact.id) || null, property_id: text(property.id) || null },
    }) : {};

    return jsonResponse(200, {
      ok: true,
      dedupe_key: dealStable,
      event_dedupe_key: eventStable,
      contact_id: text(contact.id) || null,
      property_id: text(property.id) || null,
      deal_id: text(deal.id) || null,
      activity_id: text(activity.id) || null,
      follow_up_task_id: text(followUp.id) || null,
      consent_preserved: consentResults.length > 0,
      buyer_preferences_preserved: Boolean(preferences),
      stage: "New Lead",
      assigned_to: assignedTo,
      assignment_status: text(routing.status) || null,
      assignment_override_ignored: assignmentOverrideIgnored,
      existing_owner_preserved: Boolean(existingOwner),
      outbound_communications_triggered: 0,
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
