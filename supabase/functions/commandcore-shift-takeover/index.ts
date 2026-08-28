const SERVICE_VERSION = "2026-08-28.1";
const BUCKET = "commandcore-shift-takeovers";
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

function safeSegment(value: unknown): string {
  return text(value).replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 160) || "unknown";
}

async function ensureBucket(supabaseUrl: string, serviceKey: string): Promise<void> {
  const list = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!list.ok) throw new Error("takeover_bucket_list_failed");
  const buckets = await list.json() as RecordValue[];
  if (buckets.some((bucket) => text(bucket.name || bucket.id) === BUCKET)) return;

  const created = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ id: BUCKET, name: BUCKET, public: false }),
  });
  if (!created.ok && created.status !== 409) throw new Error("takeover_bucket_create_failed");
}

async function writeTakeover(
  supabaseUrl: string,
  serviceKey: string,
  ownerId: string,
  record: RecordValue,
): Promise<void> {
  const timestamp = safeSegment(record.taken_over_at);
  const id = safeSegment(record.takeover_id);
  const path = `owners/${safeSegment(ownerId)}/${timestamp}-${id}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "false",
    },
    body: JSON.stringify(record),
  });
  if (!response.ok && response.status !== 409) throw new Error(`takeover_write_failed_${response.status}`);
}

async function listTakeovers(
  supabaseUrl: string,
  serviceKey: string,
  ownerId: string,
): Promise<RecordValue[]> {
  const prefix = `owners/${safeSegment(ownerId)}`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix, limit: 100, offset: 0, sortBy: { column: "name", order: "desc" } }),
  });
  if (!response.ok) throw new Error(`takeover_list_failed_${response.status}`);

  const rows = await response.json() as RecordValue[];
  const records: RecordValue[] = [];
  for (const row of rows) {
    const name = text(row.name);
    if (!name.endsWith(".json")) continue;
    const object = await fetch(
      `${supabaseUrl}/storage/v1/object/authenticated/${BUCKET}/${prefix}/${encodeURIComponent(name)}`,
      { headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey } },
    );
    if (!object.ok) continue;
    const parsed = await object.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) records.push(parsed as RecordValue);
  }
  return records;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-shift-takeover",
      version: SERVICE_VERSION,
      status: "healthy",
      tracking_only: true,
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
  await ensureBucket(supabaseUrl, serviceKey);

  const action = text(body.action || "takeover").toLowerCase();
  if (action === "list") {
    const records = await listTakeovers(supabaseUrl, serviceKey, ownerId);
    return jsonResponse(200, {
      ok: true,
      owner_id: ownerId,
      takeovers: records,
      latest_takeover: records[0] || null,
      total_takeovers: records.length,
    });
  }

  if (action !== "takeover") return jsonResponse(422, { ok: false, error: "unsupported_action" });

  const takenOverAt = new Date().toISOString();
  const record: RecordValue = {
    takeover_id: crypto.randomUUID(),
    owner_id: ownerId,
    owner_name: text(body.owner_name),
    taken_over_at: takenOverAt,
    brief_generated_at: text(body.brief_generated_at) || null,
    open_work_count: Number(body.open_work_count || 0),
    urgent_count: Number(body.urgent_count || 0),
    inherited_count: Number(body.inherited_count || 0),
    blocked_count: Number(body.blocked_count || 0),
    manual_count: Number(body.manual_count || 0),
    acknowledgment: "received_and_reviewed",
    note: text(body.note) || null,
    source: text(body.source) || "commandcore_my_work",
  };
  await writeTakeover(supabaseUrl, serviceKey, ownerId, record);

  return jsonResponse(200, {
    ok: true,
    takeover: record,
    assignment_changed: false,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    external_action_started: false,
  });
});
