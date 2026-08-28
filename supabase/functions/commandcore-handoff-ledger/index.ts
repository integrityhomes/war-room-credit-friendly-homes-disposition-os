const SERVICE_VERSION = "2026-08-28.1";
const BUCKET = "commandcore-handoff-ledger";
const MAX_BODY_BYTES = 128 * 1024;

type Handoff = Record<string, unknown>;

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
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

function clean(value: unknown): string {
  return String(value || "").trim();
}

function safeSegment(value: unknown): string {
  return clean(value).replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 160) || "unknown";
}

function normalizeHandoff(value: Handoff): Handoff {
  const at = clean(value.handoff_at) || new Date().toISOString();
  return {
    handoff_id: clean(value.handoff_id) || crypto.randomUUID(),
    action_id: clean(value.action_id),
    dispatch_id: clean(value.dispatch_id),
    property_id: clean(value.property_id),
    channel_key: clean(value.channel_key),
    previous_owner_id: clean(value.previous_owner_id) || null,
    previous_owner_name: clean(value.previous_owner_name) || null,
    new_owner_id: clean(value.new_owner_id || value.owner_id),
    new_owner_name: clean(value.new_owner_name || value.owner_name),
    handoff_reason: clean(value.handoff_reason || value.reassignment_reason) || "routing_change",
    routing_reason: clean(value.routing_reason),
    handoff_at: at,
    source: clean(value.source) || "commandcore",
  };
}

async function ensureBucket(supabaseUrl: string, serviceKey: string): Promise<void> {
  const list = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!list.ok) throw new Error("handoff_bucket_list_failed");
  const buckets = await list.json() as Array<Record<string, unknown>>;
  if (buckets.some((bucket) => String(bucket.name || bucket.id || "") === BUCKET)) return;
  const created = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ id: BUCKET, name: BUCKET, public: false }),
  });
  if (!created.ok && created.status !== 409) throw new Error("handoff_bucket_create_failed");
}

async function writeHandoff(supabaseUrl: string, serviceKey: string, handoff: Handoff): Promise<void> {
  const dispatch = safeSegment(handoff.dispatch_id || "unscoped");
  const timestamp = safeSegment(handoff.handoff_at);
  const id = safeSegment(handoff.handoff_id);
  const path = `dispatches/${dispatch}/${timestamp}-${id}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "false",
    },
    body: JSON.stringify(handoff),
  });
  if (!response.ok && response.status !== 409) throw new Error(`handoff_write_failed_${response.status}`);
}

async function listHandoffs(
  supabaseUrl: string,
  serviceKey: string,
  dispatchId: string,
): Promise<Handoff[]> {
  if (!dispatchId) return [];
  const prefix = `dispatches/${safeSegment(dispatchId)}`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix, limit: 1000, offset: 0, sortBy: { column: "name", order: "desc" } }),
  });
  if (!response.ok) throw new Error(`handoff_list_failed_${response.status}`);
  const rows = await response.json() as Array<Record<string, unknown>>;
  const records: Handoff[] = [];
  for (const row of rows) {
    const name = clean(row.name);
    if (!name.endsWith(".json")) continue;
    const object = await fetch(
      `${supabaseUrl}/storage/v1/object/authenticated/${BUCKET}/${prefix}/${encodeURIComponent(name)}`,
      { headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey } },
    );
    if (!object.ok) continue;
    const parsed = await object.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) records.push(parsed as Handoff);
  }
  return records;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-handoff-ledger",
      version: SERVICE_VERSION,
      status: "healthy",
      immutable_history: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw || "{}") as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });
  await ensureBucket(supabaseUrl, serviceKey);

  const action = clean(body.action || "append").toLowerCase();
  if (action === "list") {
    const dispatchId = clean(body.dispatch_id);
    if (!dispatchId) return jsonResponse(422, { ok: false, error: "dispatch_id_required" });
    const handoffs = await listHandoffs(supabaseUrl, serviceKey, dispatchId);
    return jsonResponse(200, { ok: true, dispatch_id: dispatchId, handoffs, total_handoffs: handoffs.length });
  }

  if (action === "append") {
    const supplied = Array.isArray(body.handoffs)
      ? body.handoffs.filter((item) => item && typeof item === "object") as Handoff[]
      : body.handoff && typeof body.handoff === "object" && !Array.isArray(body.handoff)
        ? [body.handoff as Handoff]
        : [];
    if (!supplied.length) return jsonResponse(422, { ok: false, error: "handoff_required" });
    const handoffs = supplied.map(normalizeHandoff);
    for (const handoff of handoffs) {
      if (!clean(handoff.action_id) || !clean(handoff.new_owner_id)) {
        return jsonResponse(422, { ok: false, error: "action_id_and_new_owner_required" });
      }
      await writeHandoff(supabaseUrl, serviceKey, handoff);
    }
    return jsonResponse(200, {
      ok: true,
      appended: handoffs.length,
      handoffs,
      readiness_changed: false,
      approval_changed: false,
      consent_changed: false,
      budget_changed: false,
      external_action_started: false,
    });
  }

  return jsonResponse(422, { ok: false, error: "unsupported_action" });
});
