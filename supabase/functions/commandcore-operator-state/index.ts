const SERVICE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 12 * 1024;
const BUCKET = "commandcore-operator-state";

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
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
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

function safePart(value: unknown): string {
  return String(value ?? "")
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

function validState(value: string): boolean {
  return ["acknowledged", "needs_follow_up", "unacknowledged"].includes(value);
}

async function saveState(body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("operator_state_not_configured");

  const actionId = safePart(body.action_id);
  const dispatchId = safePart(body.dispatch_id);
  const propertyId = safePart(body.property_id);
  const channelKey = safePart(body.channel_key);
  const state = String(body.state || "").trim();
  if (!actionId || !dispatchId || !validState(state)) throw new Error("invalid_operator_state");

  const payload = {
    action_id: actionId,
    dispatch_id: dispatchId,
    property_id: propertyId,
    channel_key: channelKey,
    state,
    note: String(body.note || "").trim().slice(0, 1000),
    updated_at: new Date().toISOString(),
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    connection_permission_changed: false,
    budget_authorization_changed: false,
    external_action_started: false,
  };

  const objectName = `actions/${actionId}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${objectName}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${serviceRoleKey}`,
      apikey: serviceRoleKey,
      "content-type": "application/json",
      "x-upsert": "true",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`operator_state_store_failed_${response.status}`);
  return payload;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-operator-state",
      version: SERVICE_VERSION,
      status: "healthy",
      allowed_states: ["acknowledged", "needs_follow_up", "unacknowledged"],
      readiness_mutation_enabled: false,
      consequential_actions_enabled: false,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  try {
    const state = await saveState(body);
    return jsonResponse(200, { ok: true, operator_state: state });
  } catch (error) {
    console.error("CommandCore operator state failed", error);
    return jsonResponse(422, {
      ok: false,
      error: "operator_state_not_saved",
      readiness_changed: false,
      external_action_started: false,
    });
  }
});
