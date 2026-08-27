const GATE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 32 * 1024;
const COMMUNICATION_CHANNELS = new Set(["email", "sms", "reactivation"]);

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function bearerToken(req: Request): string {
  const auth = req.headers.get("authorization") || "";
  return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

function isAuthenticated(req: Request): boolean {
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = bearerToken(req);
  return Boolean(serviceRoleKey && supplied && constantTimeEqual(serviceRoleKey, supplied));
}

function asBoolean(value: unknown): boolean {
  return value === true || String(value ?? "").trim().toLowerCase() === "true";
}

function normalizedString(value: unknown): string {
  return String(value ?? "").trim();
}

function configuredSenderId(channelKey: string): string {
  if (channelKey === "sms" || channelKey === "reactivation") {
    return normalizedString(Deno.env.get("COMMANDCORE_SMS_SENDER_ID"));
  }
  if (channelKey === "email") {
    return normalizedString(Deno.env.get("COMMANDCORE_EMAIL_SENDER_ID"));
  }
  return "";
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-communication-gate",
      version: GATE_VERSION,
      status: "healthy",
      external_delivery_enabled: false,
      sender_identity_required: true,
    });
  }

  if (req.method !== "POST") {
    return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  }
  if (!isAuthenticated(req)) {
    return jsonResponse(401, { ok: false, error: "unauthorized" });
  }

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

  const channelKey = normalizedString(body.channel_key).toLowerCase();
  if (!COMMUNICATION_CHANNELS.has(channelKey)) {
    return jsonResponse(422, { ok: false, error: "unsupported_communication_channel" });
  }

  const campaignApproved = asBoolean(body.campaign_approved);
  const recipientMatched = asBoolean(body.recipient_matched);
  const consentVerified = asBoolean(body.consent_verified);
  const suppressionClear = asBoolean(body.suppression_clear);
  const contentApproved = asBoolean(body.content_approved);
  const testMode = asBoolean(body.test_mode);
  const requestedSenderId = normalizedString(body.sender_id);
  const configuredSender = configuredSenderId(channelKey);
  const senderConfigured = Boolean(configuredSender);
  const senderMatches = senderConfigured && requestedSenderId === configuredSender;

  const blockers: string[] = [];
  if (!campaignApproved) blockers.push("campaign_not_approved");
  if (!recipientMatched) blockers.push("recipient_not_matched");
  if (!consentVerified) blockers.push("consent_not_verified");
  if (!suppressionClear) blockers.push("suppression_or_opt_out_block");
  if (!contentApproved) blockers.push("content_not_approved");
  if (!senderConfigured) blockers.push("approved_sender_not_configured");
  if (senderConfigured && !senderMatches) blockers.push("sender_identity_mismatch");
  if (!testMode) blockers.push("external_delivery_adapter_not_enabled");

  const canPrepare = blockers.filter((item) => item !== "external_delivery_adapter_not_enabled").length === 0;
  const canDeliver = blockers.length === 0 && testMode;

  return jsonResponse(200, {
    ok: true,
    channel_key: channelKey,
    status: canDeliver ? "test_delivery_ready" : canPrepare ? "delivery_adapter_required" : "blocked",
    campaign_approved: campaignApproved,
    recipient_matched: recipientMatched,
    consent_verified: consentVerified,
    suppression_clear: suppressionClear,
    content_approved: contentApproved,
    sender_configured: senderConfigured,
    sender_identity_matches: senderMatches,
    test_mode: testMode,
    can_prepare: canPrepare,
    can_deliver: canDeliver,
    blockers,
    external_action_started: false,
    message: canDeliver
      ? "Communication passed all safety gates for test-mode adapter validation only. No message was sent by this endpoint."
      : "Communication remains blocked until every consent, sender-identity, approval, and adapter requirement is satisfied.",
  });
});
