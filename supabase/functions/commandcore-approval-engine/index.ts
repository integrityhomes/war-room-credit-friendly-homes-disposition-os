const DISPATCH_BUCKET = "commandcore-dispatch-queue";
const APPROVAL_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 16 * 1024;

const COMMUNICATION_CHANNELS = new Set(["email", "sms", "reactivation"]);
const PAID_AD_CHANNELS = new Set(["meta_ads", "google_ads"]);
const SAFE_CONTENT_CHANNELS = new Set(["blog", "instagram", "tiktok", "youtube"]);

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

function safeQueueObject(value: unknown): string {
  const queueObject = String(value ?? "").trim();
  if (!queueObject.startsWith("dispatches/") || queueObject.includes("..")) return "";
  return queueObject;
}

async function readQueueObject(queueObject: string): Promise<Record<string, unknown>> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("approval_storage_not_configured");
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/${DISPATCH_BUCKET}/${queueObject}`,
    { method: "GET", headers: storageHeaders(serviceRoleKey) },
  );
  if (!response.ok) throw new Error(`approval_queue_read_failed_${response.status}`);
  const parsed = await response.json();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("approval_queue_payload_invalid");
  }
  return parsed as Record<string, unknown>;
}

async function writeQueueObject(queueObject: string, payload: Record<string, unknown>): Promise<void> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("approval_storage_not_configured");
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/${DISPATCH_BUCKET}/${queueObject}`,
    {
      method: "POST",
      headers: { ...storageHeaders(serviceRoleKey), "x-upsert": "true" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(`approval_queue_write_failed_${response.status}`);
}

function releaseWorkOrder(item: Record<string, unknown>, approvedBy: string, approvedAt: string) {
  const channelKey = String(item.channel_key || "").trim();
  const currentState = String(item.state || "").trim();
  if (currentState !== "awaiting_approval") return item;

  const common = {
    ...item,
    approved: true,
    approved_by: approvedBy,
    approved_at: approvedAt,
    external_action_started: false,
  };

  if (SAFE_CONTENT_CHANNELS.has(channelKey)) {
    return {
      ...common,
      state: "approved_waiting_adapter",
      result_status: "approved",
      approval_release: "content_adapter_queue",
      note: "Campaign approval released this channel for its adapter. No outside publication has started yet.",
    };
  }

  if (COMMUNICATION_CHANNELS.has(channelKey)) {
    return {
      ...common,
      state: "approved_waiting_consent_delivery_gate",
      result_status: "approved",
      approval_release: "consent_delivery_gate",
      note: "Campaign approval is recorded. Sending remains blocked until recipient consent, audience matching, and the delivery adapter all pass.",
    };
  }

  if (PAID_AD_CHANNELS.has(channelKey)) {
    return {
      ...common,
      state: "approved_waiting_budget_authorization",
      result_status: "approved",
      approval_release: "budget_gate",
      note: "Creative approval is recorded. No ad spend can start without separate budget authorization and a verified ad adapter.",
    };
  }

  return {
    ...common,
    state: "approved_waiting_adapter",
    result_status: "approved",
    approval_release: "adapter_queue",
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-approval-engine",
      version: APPROVAL_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      separate_budget_gate_enabled: true,
      consent_gate_enabled: true,
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

  const queueObject = safeQueueObject(body.queue_object);
  const approvedBy = String(body.approved_by || "").trim().slice(0, 120);
  if (!queueObject) return jsonResponse(422, { ok: false, error: "invalid_queue_object" });
  if (!approvedBy) return jsonResponse(422, { ok: false, error: "approved_by_required" });

  try {
    const queued = await readQueueObject(queueObject);
    const workOrders = Array.isArray(queued.work_orders) ? queued.work_orders : [];
    const approvedAt = new Date().toISOString();
    let released = 0;
    const updatedOrders = workOrders.map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return item;
      const before = String((item as Record<string, unknown>).state || "");
      const after = releaseWorkOrder(item as Record<string, unknown>, approvedBy, approvedAt);
      if (before === "awaiting_approval" && String((after as Record<string, unknown>).state || "") !== before) released += 1;
      return after;
    });

    const approvalRecord = {
      approved_by: approvedBy,
      approved_at: approvedAt,
      released_channels: released,
      separate_budget_gate_required: true,
      communication_consent_gate_required: true,
      external_action_started: false,
    };

    const updated = {
      ...queued,
      status: "approval_recorded",
      approval_engine_version: APPROVAL_VERSION,
      approval: approvalRecord,
      work_orders: updatedOrders,
      external_action_started: false,
    };
    await writeQueueObject(queueObject, updated);

    return jsonResponse(200, {
      ok: true,
      accepted: true,
      dispatch_id: String(queued.dispatch_id || ""),
      queue_object: queueObject,
      status: "approval_recorded",
      released_channels: released,
      approval: approvalRecord,
      channel_results: updatedOrders
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
        .map((item) => ({ channel_key: item.channel_key, status: item.result_status, state: item.state })),
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore approval engine failed", error);
    return jsonResponse(503, {
      ok: false,
      error: "approval_engine_unavailable",
      external_action_started: false,
    });
  }
});
