const MAX_BODY_BYTES = 64 * 1024;
const ALLOWED_CHANNEL_KEYS = new Set([
  "property_page",
  "facebook_groups",
  "nextdoor",
  "email",
  "sms",
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

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204 });
  }

  if (req.method !== "POST") {
    return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  }

  const secret = Deno.env.get("COMMANDCORE_ZAPIER_WEBHOOK_SECRET") || "";
  if (!secret) {
    return jsonResponse(503, { ok: false, error: "receiver_not_configured" });
  }

  const suppliedSecret = getBasicPassword(req);
  if (!suppliedSecret || !constantTimeEqual(suppliedSecret, secret)) {
    return jsonResponse(401, { ok: false, error: "unauthorized" });
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

  const channelKey = String(body.channel_key || "").trim().toLowerCase();
  const channelMode = String(body.channel_mode || "").trim().toLowerCase();
  const launchAction = String(body.launch_action || "").trim();
  const postingBlocked = body.posting_blocked === true || String(body.posting_blocked).toLowerCase() === "true";
  const requiresManualPost = body.requires_manual_post === true || String(body.requires_manual_post).toLowerCase() === "true";
  const executionAllowed = body.execution_allowed === true || String(body.execution_allowed).toLowerCase() === "true";
  const testMode = body.test_mode === true || String(body.test_mode).toLowerCase() === "true";

  if (!ALLOWED_CHANNEL_KEYS.has(channelKey)) {
    return jsonResponse(422, { ok: false, error: "unsupported_channel", channel_key: channelKey });
  }

  if (!channelMode) {
    return jsonResponse(422, { ok: false, error: "missing_channel_mode" });
  }

  // Safety gate: this receiver accepts and validates the handoff, but it must never
  // cause a live external action unless every upstream gate explicitly allows it.
  const canExecute = executionAllowed && !postingBlocked && !requiresManualPost && !testMode;

  return jsonResponse(200, {
    ok: true,
    status: canExecute ? "accepted_for_execution" : "accepted_no_execution",
    channel_key: channelKey,
    channel_mode: channelMode,
    launch_action: launchAction,
    execution_allowed: executionAllowed,
    posting_blocked: postingBlocked,
    requires_manual_post: requiresManualPost,
    test_mode: testMode,
    external_action_started: false,
    message: canExecute
      ? "Validated by CommandCore receiver. No external action is started by this endpoint yet."
      : "Validated safely. No external action was started.",
  });
});
