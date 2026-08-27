const MAX_BODY_BYTES = 64 * 1024;
const RECEIVER_VERSION = "2026-08-27.4";

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

function getBearerToken(req: Request): string | null {
  const auth = req.headers.get("authorization") || "";
  if (!auth.startsWith("Bearer ")) return null;
  return auth.slice(7).trim() || null;
}

function requestIsAuthenticated(req: Request): boolean {
  const webhookSecret = Deno.env.get("COMMANDCORE_ZAPIER_WEBHOOK_SECRET") || "";
  const suppliedBasic = getBasicPassword(req) || "";
  if (webhookSecret && suppliedBasic && constantTimeEqual(suppliedBasic, webhookSecret)) {
    return true;
  }

  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const suppliedBearer = getBearerToken(req) || "";
  return Boolean(
    serviceRoleKey && suppliedBearer && constantTimeEqual(suppliedBearer, serviceRoleKey),
  );
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

function routingDecision(row: ReturnType<typeof normalizedChannelResult>) {
  if (row.posting_blocked) {
    return { ...row, route: "blocked", next_step: "hold" };
  }
  if (row.requires_manual_post) {
    return { ...row, route: "manual_final_post", next_step: "prepare_package" };
  }
  if (row.channel_mode === "Approval Required") {
    return { ...row, route: "approval_queue", next_step: "await_approval" };
  }
  if (row.channel_mode === "Automatic") {
    return {
      ...row,
      route: row.can_execute ? "automatic_execution" : "automatic_ready",
      next_step: row.can_execute ? "execute_adapter" : "await_adapter_enablement",
    };
  }
  return { ...row, route: "review", next_step: "review_configuration" };
}

function routingSummary(rows: ReturnType<typeof routingDecision>[]) {
  const count = (route: string) => rows.filter((row) => row.route === route).length;
  return {
    total: rows.length,
    automatic_execution: count("automatic_execution"),
    automatic_ready: count("automatic_ready"),
    approval_queue: count("approval_queue"),
    manual_final_post: count("manual_final_post"),
    blocked: count("blocked"),
    review: count("review"),
  };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }

  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-channel-receiver",
      version: RECEIVER_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      dispatcher_enabled: true,
    });
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

  const authenticated = requestIsAuthenticated(req);

  if (body.event === "credit_friendly_homes.campaign.approved" && Array.isArray(body.channels)) {
    const normalized = (body.channels as unknown[])
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
      .map((item) => normalizedChannelResult(item, authenticated));

    const invalid = normalized.filter(
      (row) => !CHANNEL_MODE_BY_KEY[row.channel_key] || !row.channel_mode,
    );
    if (invalid.length) {
      return jsonResponse(422, {
        ok: false,
        error: "unsupported_or_invalid_channel",
        channels: invalid.map((row) => row.channel_key),
      });
    }

    const rows = normalized.map(routingDecision);
    return jsonResponse(200, {
      ok: true,
      status: "accepted_and_routed",
      handoff_mode: "full_campaign_payload",
      authenticated,
      dispatcher_enabled: true,
      channel_count: rows.length,
      routing_summary: routingSummary(rows),
      channels: rows,
      external_action_started: false,
      message: authenticated
        ? "CommandCore accepted and routed the complete CFH campaign. External adapters remain disabled until individually enabled."
        : "CommandCore accepted and routed the campaign in forced-safe setup mode. No external action was started.",
    });
  }

  const channelKey = String(body.channel_key || "").trim().toLowerCase();
  if (!CHANNEL_MODE_BY_KEY[channelKey]) {
    return jsonResponse(422, {
      ok: false,
      error: "unsupported_channel",
      channel_key: channelKey,
    });
  }

  const result = routingDecision(normalizedChannelResult(body, authenticated));
  return jsonResponse(200, {
    ok: true,
    status: "accepted_and_routed",
    ...result,
    authenticated,
    dispatcher_enabled: true,
    external_action_started: false,
    message: "CommandCore routed this channel safely. No external action was started by this endpoint.",
  });
});
