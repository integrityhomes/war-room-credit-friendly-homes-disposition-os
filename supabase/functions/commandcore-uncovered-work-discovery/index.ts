const SERVICE_VERSION = "2026-08-28.1";
const ACTION_BUCKET = "commandcore-action-queue";
const MAX_BODY_BYTES = 64 * 1024;

type RecordValue = Record<string, unknown>;

function jsonResponse(status: number, payload: RecordValue): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function isAuthenticated(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const auth = req.headers.get("authorization") || "";
  const supplied = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function text(value: unknown): string {
  return String(value || "").trim();
}

function isOpenItem(item: RecordValue): boolean {
  const state = text(item.state || item.operator_state || item.status).toLowerCase();
  const completedAt = text(item.completed_at || item.resolved_at || item.closed_at);
  if (completedAt) return false;
  return !["done", "completed", "resolved", "closed", "cancelled", "canceled"].includes(state);
}

async function listDispatchFiles(supabaseUrl: string, serviceKey: string): Promise<RecordValue[]> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${ACTION_BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix: "dispatches", limit: 1000, offset: 0, sortBy: { column: "updated_at", order: "desc" } }),
  });
  if (!response.ok) throw new Error(`action_queue_list_failed_${response.status}`);
  const parsed = await response.json();
  return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") as RecordValue[] : [];
}

async function loadDispatch(
  supabaseUrl: string,
  serviceKey: string,
  filename: string,
): Promise<RecordValue | null> {
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/authenticated/${ACTION_BUCKET}/dispatches/${encodeURIComponent(filename)}`,
    { headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey } },
  );
  if (!response.ok) return null;
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as RecordValue : null;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-uncovered-work-discovery",
      version: SERVICE_VERSION,
      status: "healthy",
      discovery_only: true,
      external_execution_enabled: false,
      assignment_mutation_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: RecordValue;
  try {
    body = JSON.parse(raw || "{}") as RecordValue;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const ownerId = text(body.owner_id);
  if (!ownerId) return jsonResponse(422, { ok: false, error: "owner_id_required" });

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const files = await listDispatchFiles(supabaseUrl, serviceKey);
  const ownerKey = ownerId.toLowerCase();
  const uncovered: RecordValue[] = [];

  for (const file of files) {
    const filename = text(file.name);
    if (!filename.endsWith(".json")) continue;
    const queue = await loadDispatch(supabaseUrl, serviceKey, filename);
    if (!queue) continue;
    const dispatchId = text(queue.dispatch_id) || filename.replace(/\.json$/i, "");
    const items = Array.isArray(queue.items)
      ? queue.items.filter((item) => item && typeof item === "object") as RecordValue[]
      : [];
    const ownedOpenItems = items.filter((item) => text(item.owner_id).toLowerCase() === ownerKey && isOpenItem(item));
    if (!ownedOpenItems.length) continue;

    uncovered.push({
      dispatch_id: dispatchId,
      property_id: text(queue.property_id || ownedOpenItems[0]?.property_id),
      open_item_count: ownedOpenItems.length,
      high_priority_count: ownedOpenItems.filter((item) => text(item.priority).toLowerCase() === "high").length,
      blocked_count: ownedOpenItems.filter((item) => text(item.readiness).toUpperCase() === "BLOCKED").length,
      manual_count: ownedOpenItems.filter((item) => text(item.readiness).toUpperCase() === "MANUAL").length,
      channels: [...new Set(ownedOpenItems.map((item) => text(item.channel_key)).filter(Boolean))],
      action_ids: ownedOpenItems.map((item) => text(item.action_id || `${dispatchId}_${text(item.channel_key)}`)).filter(Boolean),
    });
  }

  uncovered.sort((left, right) => {
    const leftUrgency = Number(left.blocked_count || 0) * 100 + Number(left.high_priority_count || 0) * 10 + Number(left.manual_count || 0);
    const rightUrgency = Number(right.blocked_count || 0) * 100 + Number(right.high_priority_count || 0) * 10 + Number(right.manual_count || 0);
    return rightUrgency - leftUrgency || text(left.dispatch_id).localeCompare(text(right.dispatch_id));
  });

  return jsonResponse(200, {
    ok: true,
    owner_id: ownerId,
    dispatch_count: uncovered.length,
    open_item_count: uncovered.reduce((total, item) => total + Number(item.open_item_count || 0), 0),
    uncovered_dispatches: uncovered,
    dispatch_ids: uncovered.map((item) => item.dispatch_id),
    assignment_changed: false,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    external_action_started: false,
  });
});
