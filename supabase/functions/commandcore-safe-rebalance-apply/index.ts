const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 128 * 1024;
const ACTION_BUCKET = "commandcore-action-queue";

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
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

function memberId(member: Row): string {
  return text(member.id || member.user_id || member.email || member.name);
}

function maxLoad(member: Row): number {
  const value = Number(member.max_load ?? 20);
  return Number.isFinite(value) && value > 0 ? value : 20;
}

function isOpen(item: Row): boolean {
  return ["hold", "manual", "blocked"].includes(text(item.readiness).toLowerCase());
}

async function callService(
  supabaseUrl: string,
  serviceKey: string,
  service: string,
  payload: Row,
): Promise<Row> {
  const response = await fetch(`${supabaseUrl}/functions/v1/${service}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${service}_unavailable`);
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : {};
}

async function loadQueue(supabaseUrl: string, serviceKey: string, dispatchId: string): Promise<Row> {
  const path = `dispatches/${encodeURIComponent(dispatchId)}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/authenticated/${ACTION_BUCKET}/${path}`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!response.ok) throw new Error(`action_queue_read_failed_${response.status}`);
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : {};
}

async function persistQueue(supabaseUrl: string, serviceKey: string, dispatchId: string, queue: Row): Promise<void> {
  const path = `dispatches/${encodeURIComponent(dispatchId)}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${ACTION_BUCKET}/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "true",
    },
    body: JSON.stringify(queue),
  });
  if (!response.ok) throw new Error(`action_queue_write_failed_${response.status}`);
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-safe-rebalance-apply",
      version: SERVICE_VERSION,
      status: "healthy",
      assignment_only: true,
      requires_explicit_apply: true,
      external_execution_enabled: false,
      readiness_mutation_enabled: false,
      approval_mutation_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Row;
  try {
    body = JSON.parse(raw) as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const apply = body.apply === true;
  if (!apply) return jsonResponse(422, { ok: false, error: "explicit_apply_required" });

  const dispatchId = text(body.dispatch_id);
  const actionId = text(body.action_id);
  const expectedFromOwnerId = text(body.from_owner_id);
  const toOwnerId = text(body.to_owner_id);
  if (!dispatchId || !actionId || !toOwnerId) {
    return jsonResponse(422, { ok: false, error: "dispatch_action_and_target_required" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const [registry, coverageResult, queue] = await Promise.all([
    callService(supabaseUrl, serviceKey, "commandcore-team-registry", { action: "list" }),
    callService(supabaseUrl, serviceKey, "commandcore-team-coverage", {}),
    loadQueue(supabaseUrl, serviceKey, dispatchId),
  ]);

  const members = Array.isArray(registry.members) ? registry.members.filter((item) => item && typeof item === "object") as Row[] : [];
  const target = members.find((member) => memberId(member).toLowerCase() === toOwnerId.toLowerCase());
  if (!target || target.active === false) return jsonResponse(409, { ok: false, error: "target_owner_not_active" });

  const coverage = Array.isArray(coverageResult.coverage)
    ? coverageResult.coverage.filter((item) => item && typeof item === "object") as Row[]
    : [];
  const targetCoverage = coverage.find((item) => text(item.id).toLowerCase() === toOwnerId.toLowerCase());
  if (!targetCoverage || targetCoverage.available !== true) {
    return jsonResponse(409, { ok: false, error: "target_owner_not_available" });
  }

  const items = Array.isArray(queue.items) ? queue.items.filter((item) => item && typeof item === "object") as Row[] : [];
  const targetLoad = items.filter((item) => isOpen(item) && text(item.owner_id).toLowerCase() === toOwnerId.toLowerCase()).length;
  if (targetLoad >= maxLoad(target)) return jsonResponse(409, { ok: false, error: "target_owner_at_capacity" });

  let changed = false;
  let handoff: Row | null = null;
  const updatedItems = items.map((item) => {
    if (text(item.action_id) !== actionId) return item;
    const currentOwnerId = text(item.owner_id);
    if (expectedFromOwnerId && currentOwnerId.toLowerCase() !== expectedFromOwnerId.toLowerCase()) {
      return item;
    }
    if (!isOpen(item)) return item;

    changed = true;
    const now = new Date().toISOString();
    handoff = {
      action_id: actionId,
      dispatch_id: dispatchId,
      property_id: text(item.property_id),
      channel_key: text(item.channel_key),
      previous_owner_id: currentOwnerId || null,
      previous_owner_name: text(item.owner_name) || null,
      new_owner_id: memberId(target),
      new_owner_name: text(target.name || memberId(target)),
      handoff_reason: "safe_workload_rebalance",
      routing_reason: text(body.reason || "advisor_recommendation"),
      handoff_at: now,
      source: "commandcore-safe-rebalance-apply",
    };
    return {
      ...item,
      owner_id: memberId(target),
      owner_name: text(target.name || memberId(target)),
      assignment_status: "assigned",
      routing_reason: text(body.reason || "advisor_recommendation"),
      reassignment_reason: "safe_workload_rebalance",
      reassigned_at: now,
      workload_after_assignment: targetLoad + 1,
    };
  });

  if (!changed || !handoff) {
    return jsonResponse(409, { ok: false, error: "recommendation_stale_or_action_not_found" });
  }

  await persistQueue(supabaseUrl, serviceKey, dispatchId, { ...queue, items: updatedItems });
  await callService(supabaseUrl, serviceKey, "commandcore-handoff-ledger", { action: "append", handoffs: [handoff] });

  return jsonResponse(200, {
    ok: true,
    applied: true,
    dispatch_id: dispatchId,
    action_id: actionId,
    from_owner_id: expectedFromOwnerId || null,
    to_owner_id: memberId(target),
    assignment_changed: true,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    external_action_started: false,
  });
});
