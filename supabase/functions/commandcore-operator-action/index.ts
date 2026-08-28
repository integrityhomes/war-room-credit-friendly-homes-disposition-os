const SERVICE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 12 * 1024;

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

function queueObjectFrom(body: Record<string, unknown>): string {
  const explicit = String(body.queue_object || "").trim();
  if (explicit) return explicit;
  const dispatchId = safePart(body.dispatch_id);
  const propertyId = safePart(body.property_id);
  return dispatchId && propertyId ? `dispatches/${propertyId}/${dispatchId}.json` : "";
}

function validQueueObject(value: string): boolean {
  return value.startsWith("dispatches/") && value.endsWith(".json") && !value.includes("..") && value.length <= 320;
}

async function callDispatchWorker(queueObject: string): Promise<Record<string, unknown>> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("operator_action_not_configured");

  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-dispatch-worker`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${serviceRoleKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ queue_object: queueObject }),
  });
  const text = await response.text();
  let result: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) result = parsed as Record<string, unknown>;
  } catch {
    // Keep an empty structured result below.
  }
  if (!response.ok) throw new Error(`dispatch_retry_failed_${response.status}`);
  return result;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-operator-action",
      version: SERVICE_VERSION,
      status: "healthy",
      allowed_actions: ["retry_internal_dispatch"],
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

  const action = String(body.action || "").trim();
  if (action !== "retry_internal_dispatch") {
    return jsonResponse(403, {
      ok: false,
      error: "operator_action_not_permitted",
      allowed_actions: ["retry_internal_dispatch"],
      consequential_actions_enabled: false,
      external_action_started: false,
    });
  }

  const queueObject = queueObjectFrom(body);
  if (!validQueueObject(queueObject)) return jsonResponse(422, { ok: false, error: "invalid_queue_object", external_action_started: false });

  try {
    const result = await callDispatchWorker(queueObject);
    return jsonResponse(200, {
      ok: true,
      action,
      queue_object: queueObject,
      dispatch_result: result,
      safe_internal_retry_completed: true,
      approval_changed: false,
      consent_changed: false,
      connection_permission_changed: false,
      budget_authorization_changed: false,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore operator action failed", error);
    return jsonResponse(503, {
      ok: false,
      error: "operator_action_unavailable",
      safe_internal_retry_completed: false,
      external_action_started: false,
    });
  }
});
