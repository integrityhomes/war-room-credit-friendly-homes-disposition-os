const DISPATCH_BUCKET = "commandcore-dispatch-queue";
const WORKER_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 16 * 1024;

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

function storageHeaders(serviceRoleKey: string): HeadersInit {
  return {
    authorization: `Bearer ${serviceRoleKey}`,
    apikey: serviceRoleKey,
    "content-type": "application/json",
  };
}

function safePart(value: unknown): string {
  return String(value ?? "")
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 120);
}

async function readQueueObject(queueObject: string): Promise<Record<string, unknown>> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("worker_storage_not_configured");

  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/${DISPATCH_BUCKET}/${queueObject}`,
    { method: "GET", headers: storageHeaders(serviceRoleKey) },
  );
  if (!response.ok) throw new Error(`queue_read_failed_${response.status}`);
  const parsed = await response.json();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("queue_payload_invalid");
  }
  return parsed as Record<string, unknown>;
}

async function writeQueueObject(queueObject: string, payload: Record<string, unknown>): Promise<void> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("worker_storage_not_configured");

  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/${DISPATCH_BUCKET}/${queueObject}`,
    {
      method: "POST",
      headers: { ...storageHeaders(serviceRoleKey), "x-upsert": "true" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(`queue_update_failed_${response.status}`);
}

function buildWorkOrders(queued: Record<string, unknown>) {
  const routes = Array.isArray(queued.routes) ? queued.routes : [];
  return routes
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    .map((route) => {
      const channelKey = String(route.channel_key || "").trim();
      const routeName = String(route.route || "").trim();

      if (channelKey === "property_page" && routeName === "automatic_ready") {
        return {
          channel_key: channelKey,
          adapter: "cfh_internal_property_page",
          state: "confirmed_internal_live",
          external_action_required: false,
          external_action_started: false,
          result_status: "live",
          note: "Property landing pages are rendered from the approved CFH property record; no outside platform action is required.",
        };
      }

      if (channelKey === "market_seo" && routeName === "automatic_ready") {
        return {
          channel_key: channelKey,
          adapter: "cfh_market_seo",
          state: "adapter_build_required",
          external_action_required: false,
          external_action_started: false,
          result_status: "awaiting_adapter",
          note: "City and market SEO remains queued until its internal adapter is built and verified.",
        };
      }

      if (routeName === "approval_queue") {
        return {
          channel_key: channelKey,
          adapter: "approval_gate",
          state: "awaiting_approval",
          external_action_required: true,
          external_action_started: false,
          result_status: "awaiting_approval",
        };
      }

      if (routeName === "manual_final_post") {
        return {
          channel_key: channelKey,
          adapter: "manual_final_post",
          state: "package_ready_for_human",
          external_action_required: true,
          external_action_started: false,
          result_status: "ready",
        };
      }

      if (routeName === "blocked") {
        return {
          channel_key: channelKey,
          adapter: "safety_hold",
          state: "blocked",
          external_action_required: false,
          external_action_started: false,
          result_status: "blocked",
        };
      }

      return {
        channel_key: channelKey,
        adapter: "unassigned",
        state: "review_required",
        external_action_required: false,
        external_action_started: false,
        result_status: "review",
      };
    });
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-dispatch-worker",
      version: WORKER_VERSION,
      status: "healthy",
      external_execution_enabled: false,
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

  const dispatchId = safePart(body.dispatch_id);
  const propertyId = safePart(body.property_id);
  const queueObject = safePart(body.queue_object)
    ? String(body.queue_object)
    : dispatchId && propertyId
      ? `dispatches/${propertyId}/${dispatchId}.json`
      : "";

  if (!queueObject.startsWith("dispatches/") || queueObject.includes("..")) {
    return jsonResponse(422, { ok: false, error: "invalid_queue_object" });
  }

  try {
    const queued = await readQueueObject(queueObject);
    const workOrders = buildWorkOrders(queued);
    const updated = {
      ...queued,
      status: "adapter_work_prepared",
      worker_version: WORKER_VERSION,
      worker_processed_at: new Date().toISOString(),
      work_orders: workOrders,
      external_action_started: false,
    };
    await writeQueueObject(queueObject, updated);

    return jsonResponse(200, {
      ok: true,
      accepted: true,
      dispatch_id: String(queued.dispatch_id || dispatchId),
      queue_object: queueObject,
      status: "adapter_work_prepared",
      work_order_count: workOrders.length,
      channel_results: workOrders.map((item) => ({
        channel_key: item.channel_key,
        status: item.result_status,
      })),
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore dispatch worker failed", error);
    return jsonResponse(503, {
      ok: false,
      error: "dispatch_worker_unavailable",
      external_action_started: false,
    });
  }
});
