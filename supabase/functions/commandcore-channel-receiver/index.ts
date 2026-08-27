const MAX_BODY_BYTES = 64 * 1024;

const CHANNEL_MODE_BY_KEY: Record<string, string> = {
  property_page: "Automatic",
  blog: "Approval Required",
  market_seo: "Automatic",
  email: "Approval Required",
  sms: "Approval Required",
  reactivation: "Approval Required",
  marketplace: "Assisted Posting",
  facebook_groups: "Assisted Posting",
  meta_ads: "Approval Required",
  google_ads: "Approval Required",
  instagram: "Approval Required",
  tiktok: "Approval Required",
  youtube: "Approval Required",
  classifieds: "Assisted Posting",
  nextdoor: "Assisted Posting",
};

const MANUAL_FINAL_POST_CHANNELS = new Set([
  "marketplace",
  "facebook_groups",
  "classifieds",
  "nextdoor",
]);

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
  for (let i = 0; i < left.length; i += 1) {
    difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return difference === 0;
}

function getBasicPassword(req: Request): string | null {
  const auth = req.headers.get("authorization") || "";
  if (!auth.startsWith("Basic ")) return null;
  try {
    const decoded = atob(auth.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return decoded.slice(separator + 1);
  } catch {
    return null;
  }
}

function asBoolean(value: unknown): boolean {
  return value === true || String(value ?? "").toLowerCase() === "true";
}

function normalizedChannelResult(row: Record<string, unknown>, authenticated: boolean) {
  const channelKey = String(row.channel_key || "").trim().toLowerCase();
  const channelMode = String(row.channel_mode || CHANNEL_MODE_BY_KEY[channelKey] || "").trim();
  const launchAction = String(row.launch_action || "").trim();
  const postingBlocked = asBoolean(row.posting_blocked);
  const requiresManualPost =
    asBoolean(row.requires_manual_post) ||
    asBoolean(row.requires_manual_final_post) ||
    MANUAL_FINAL_POST_CHANNELS.has(channelKey);
  const executionAllowed = authenticated && asBoolean(row.execution_allowed);
  const testMode = !authenticated || asBoolean(row.test_mode);
  const canExecute =
    authenticated &&
    executionAllowed &&
    !postingBlocked &&
    !requiresManualPost &&
    !testMode;

  return {
    channel_key: channelKey,
    channel_mode: channelMode,
    launch_action: launchAction,
    execution_allowed: executionAllowed,
    posting_blocked: postingBlocked,
    requires_manual_post: requiresManualPost,
    test_mode: testMode,
    can_execute: canExecute,
  };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }

  if (req.method !== "POST") {
    return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  }

  const contentLength = Number(req.headers.get("content-length") || "0");
  if (contentLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
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

  // Authentication is required before this receiver is ever allowed to execute
  // an external action. During setup/testing, an unauthenticated Zapier request
  // is permitted only in forced-safe inspection mode. It cannot execute, publish,
  // send, spend money, or persist an external action.
  const secret = Deno.env.get("COMMANDCORE_ZAPIER_WEBHOOK_SECRET") || "";
  const suppliedSecret = getBasicPassword(req) || "";
  const authenticated = Boolean(secret && suppliedSecret && constantTimeEqual(suppliedSecret, secret));

  // Automation-first full campaign handoff. This lets CommandCore accept the
  // complete CFH launch payload in one POST rather than requiring dozens of
  // Zapier key/value mappings.
  if (body.event === "credit_friendly_homes.campaign.approved" && Array.isArray(body.channels)) {
    const rows = (body.channels as unknown[])
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
      .map((item) => normalizedChannelResult(item, authenticated));

    const invalid = rows.filter(
      (row) => !CHANNEL_MODE_BY_KEY[row.channel_key] || !row.channel_mode,
    );
    if (invalid.length) {
      return jsonResponse(422, {
        ok: false,
        error: "unsupported_or_invalid_channel",
        channels: invalid.map((row) => row.channel_key),
      });
    }

    return jsonResponse(200, {
      ok: true,
      status: "accepted_no_execution",
      handoff_mode: "full_campaign_payload",
      authenticated,
      channel_count: rows.length,
      channels: rows,
      external_action_started: false,
      message: authenticated
        ? "CommandCore accepted the complete campaign payload. External execution remains disabled in this receiver version."
        : "CommandCore accepted the complete campaign payload in forced-safe setup mode. No external action was started.",
    });
  }

  // Backward-compatible single-channel handoff. Missing mode/action fields are
  // derived safely so Zapier setup does not require field-by-field manual work.
  const channelKey = String(body.channel_key || "").trim().toLowerCase();
  if (!CHANNEL_MODE_BY_KEY[channelKey]) {
    return jsonResponse(422, {
      ok: false,
      error: "unsupported_channel",
      channel_key: channelKey,
    });
  }

  const result = normalizedChannelResult(body, authenticated);
  return jsonResponse(200, {
    ok: true,
    status: result.can_execute ? "accepted_for_execution" : "accepted_no_execution",
    ...result,
    authenticated,
    external_action_started: false,
    message: result.can_execute
      ? "Validated by CommandCore receiver. No external action is started by this endpoint yet."
      : authenticated
        ? "Validated safely. No external action was started."
        : "Validated in forced-safe setup mode. Authentication will be required before any live execution is enabled.",
  });
});
