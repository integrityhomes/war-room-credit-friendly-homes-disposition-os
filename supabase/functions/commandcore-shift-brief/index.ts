const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 64 * 1024;
const ACTION_BUCKET = "commandcore-action-queue";

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
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
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

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : [];
}

function actionId(item: RecordValue): string {
  return text(item.action_id || `${item.dispatch_id || ""}_${item.channel_key || ""}`);
}

function priorityRank(item: RecordValue): number {
  const priority = text(item.priority).toLowerCase();
  const readiness = text(item.readiness).toUpperCase();
  if (readiness === "BLOCKED") return 0;
  if (priority === "high") return 1;
  if (readiness === "MANUAL") return 2;
  if (priority === "medium") return 3;
  return 4;
}

async function listQueueSnapshots(supabaseUrl: string, serviceKey: string): Promise<RecordValue[]> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${ACTION_BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix: "dispatches", limit: 1000, offset: 0, sortBy: { column: "name", order: "desc" } }),
  });
  if (!response.ok) throw new Error(`action_queue_list_failed_${response.status}`);
  const rows = await response.json() as RecordValue[];
  const snapshots: RecordValue[] = [];
  for (const row of rows) {
    const name = text(row.name);
    if (!name.endsWith(".json")) continue;
    const object = await fetch(
      `${supabaseUrl}/storage/v1/object/authenticated/${ACTION_BUCKET}/dispatches/${encodeURIComponent(name)}`,
      { headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey } },
    );
    if (!object.ok) continue;
    const parsed = await object.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) snapshots.push(parsed as RecordValue);
  }
  return snapshots;
}

async function loadHandoffs(
  supabaseUrl: string,
  serviceKey: string,
  dispatchId: string,
): Promise<RecordValue[]> {
  if (!dispatchId) return [];
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-handoff-ledger`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({ action: "list", dispatch_id: dispatchId }),
  });
  if (!response.ok) return [];
  const parsed = await response.json() as RecordValue;
  return Array.isArray(parsed.handoffs)
    ? parsed.handoffs.filter((item) => item && typeof item === "object") as RecordValue[]
    : [];
}

function summarizeItem(item: RecordValue, history: RecordValue[]): RecordValue {
  const id = actionId(item);
  const matching = history.filter((entry) => text(entry.action_id) === id);
  const lastHandoff = matching[0] || null;
  return {
    action_id: id,
    dispatch_id: text(item.dispatch_id),
    property_id: text(item.property_id),
    channel_key: text(item.channel_key),
    priority: text(item.priority || "medium").toLowerCase(),
    readiness: text(item.readiness || "HOLD").toUpperCase(),
    required_actions: stringList(item.required_actions),
    reasons: stringList(item.reasons),
    current_owner_id: text(item.owner_id),
    current_owner_name: text(item.owner_name),
    reassignment_reason: text(item.reassignment_reason),
    reassigned_at: text(item.reassigned_at) || null,
    handoff_count: matching.length,
    last_handoff: lastHandoff,
    urgent: priorityRank(item) <= 2,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-shift-handoff-brief",
      version: SERVICE_VERSION,
      status: "healthy",
      read_only: true,
      external_execution_enabled: false,
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

  const snapshots = await listQueueSnapshots(supabaseUrl, serviceKey);
  const items: RecordValue[] = [];
  for (const snapshot of snapshots) {
    const dispatchId = text(snapshot.dispatch_id || snapshot.id);
    const queueItems = Array.isArray(snapshot.items)
      ? snapshot.items.filter((item) => item && typeof item === "object") as RecordValue[]
      : [];
    for (const item of queueItems) {
      if (text(item.owner_id).toLowerCase() !== ownerId.toLowerCase()) continue;
      items.push({ ...item, dispatch_id: text(item.dispatch_id) || dispatchId });
    }
  }

  const dispatchIds = [...new Set(items.map((item) => text(item.dispatch_id)).filter(Boolean))];
  const histories = new Map<string, RecordValue[]>();
  for (const dispatchId of dispatchIds) {
    histories.set(dispatchId, await loadHandoffs(supabaseUrl, serviceKey, dispatchId));
  }

  const briefItems = items
    .map((item) => summarizeItem(item, histories.get(text(item.dispatch_id)) || []))
    .sort((left, right) => priorityRank(left) - priorityRank(right));

  const urgent = briefItems.filter((item) => item.urgent === true);
  const inherited = briefItems.filter((item) => Number(item.handoff_count || 0) > 0);
  const blocked = briefItems.filter((item) => text(item.readiness) === "BLOCKED");
  const manual = briefItems.filter((item) => text(item.readiness) === "MANUAL");

  return jsonResponse(200, {
    ok: true,
    owner_id: ownerId,
    generated_at: new Date().toISOString(),
    total_open_work: briefItems.length,
    urgent_count: urgent.length,
    inherited_count: inherited.length,
    blocked_count: blocked.length,
    manual_count: manual.length,
    executive_summary: {
      needs_attention_now: urgent.length,
      inherited_from_other_owners: inherited.length,
      blocked_items: blocked.length,
      manual_items: manual.length,
    },
    items: briefItems,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    assignment_changed: false,
    external_action_started: false,
  });
});
