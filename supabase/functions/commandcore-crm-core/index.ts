const SERVICE_VERSION = "2026-08-28.1";
const BUCKET = "commandcore-crm-core";
const MAX_BODY_BYTES = 256 * 1024;
const MAX_LIST = 500;

const ENTITY_TYPES = new Set([
  "contacts",
  "properties",
  "deals",
  "activities",
  "communications",
  "tasks",
  "offers",
  "documents",
  "transactions",
]);

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function text(value: unknown): string {
  return String(value || "").trim();
}

function safeSegment(value: unknown): string {
  return text(value).replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 180) || "unknown";
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

function normalizeEntity(value: unknown): string {
  const entity = text(value).toLowerCase();
  return ENTITY_TYPES.has(entity) ? entity : "";
}

function deterministicImportId(entity: string, source: string, externalId: string): string {
  const input = `${entity}:${source.toLowerCase()}:${externalId.toLowerCase()}`;
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `imp-${Math.abs(hash >>> 0).toString(36)}-${safeSegment(externalId).slice(0, 72)}`;
}

async function ensureBucket(supabaseUrl: string, serviceKey: string): Promise<void> {
  const response = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!response.ok) throw new Error("crm_bucket_list_failed");
  const buckets = await response.json() as Row[];
  if (buckets.some((bucket) => text(bucket.id || bucket.name) === BUCKET)) return;
  const created = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ id: BUCKET, name: BUCKET, public: false }),
  });
  if (!created.ok && created.status !== 409) throw new Error("crm_bucket_create_failed");
}

function recordPath(entity: string, id: string): string {
  return `${entity}/${safeSegment(id)}.json`;
}

async function readRecord(supabaseUrl: string, serviceKey: string, entity: string, id: string): Promise<Row | null> {
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/authenticated/${BUCKET}/${recordPath(entity, id)}`,
    { headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey } },
  );
  if (response.status === 404 || response.status === 400) return null;
  if (!response.ok) throw new Error(`crm_record_read_failed_${response.status}`);
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : null;
}

async function writeRecord(
  supabaseUrl: string,
  serviceKey: string,
  entity: string,
  id: string,
  record: Row,
): Promise<void> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${recordPath(entity, id)}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "true",
    },
    body: JSON.stringify(record),
  });
  if (!response.ok) throw new Error(`crm_record_write_failed_${response.status}`);
}

async function listRecords(
  supabaseUrl: string,
  serviceKey: string,
  entity: string,
  limit: number,
): Promise<Row[]> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      prefix: entity,
      limit: Math.min(Math.max(limit, 1), MAX_LIST),
      offset: 0,
      sortBy: { column: "updated_at", order: "desc" },
    }),
  });
  if (!response.ok) throw new Error(`crm_record_list_failed_${response.status}`);
  const rows = await response.json() as Row[];
  const records: Row[] = [];
  for (const row of rows) {
    const name = text(row.name);
    if (!name.endsWith(".json")) continue;
    const id = name.slice(0, -5);
    const record = await readRecord(supabaseUrl, serviceKey, entity, id);
    if (record) records.push(record);
  }
  return records;
}

function normalizeRecord(entity: string, supplied: Row, existing: Row | null): Row {
  const now = new Date().toISOString();
  const source = text(supplied.source || existing?.source || "commandcore");
  const externalId = text(supplied.external_id || existing?.external_id);
  const suppliedId = text(supplied.id || supplied[`${entity.slice(0, -1)}_id`]);
  const id = suppliedId || (externalId ? deterministicImportId(entity, source, externalId) : crypto.randomUUID());

  const links = supplied.links && typeof supplied.links === "object" && !Array.isArray(supplied.links)
    ? supplied.links as Row
    : existing?.links && typeof existing.links === "object" && !Array.isArray(existing.links)
      ? existing.links as Row
      : {};

  return {
    ...(existing || {}),
    ...supplied,
    id,
    entity_type: entity,
    source,
    external_id: externalId || null,
    links,
    created_at: text(existing?.created_at || supplied.created_at) || now,
    updated_at: now,
    archived: supplied.archived === true,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-crm-core",
      version: SERVICE_VERSION,
      status: "healthy",
      entity_types: [...ENTITY_TYPES],
      migration_safe_external_ids: true,
      destructive_delete_enabled: false,
      external_execution_enabled: false,
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
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });
  await ensureBucket(supabaseUrl, serviceKey);

  const action = text(body.action || "upsert").toLowerCase();
  const entity = normalizeEntity(body.entity);
  if (!entity) return jsonResponse(422, { ok: false, error: "valid_entity_required", entity_types: [...ENTITY_TYPES] });

  if (action === "get") {
    const id = text(body.id);
    if (!id) return jsonResponse(422, { ok: false, error: "id_required" });
    const record = await readRecord(supabaseUrl, serviceKey, entity, id);
    return record
      ? jsonResponse(200, { ok: true, entity, record })
      : jsonResponse(404, { ok: false, error: "record_not_found", entity, id });
  }

  if (action === "list") {
    const limit = Number(body.limit || 100);
    const records = await listRecords(supabaseUrl, serviceKey, entity, Number.isFinite(limit) ? limit : 100);
    const includeArchived = body.include_archived === true;
    const filtered = includeArchived ? records : records.filter((record) => record.archived !== true);
    return jsonResponse(200, { ok: true, entity, records: filtered, count: filtered.length });
  }

  if (action === "archive") {
    const id = text(body.id);
    if (!id) return jsonResponse(422, { ok: false, error: "id_required" });
    const existing = await readRecord(supabaseUrl, serviceKey, entity, id);
    if (!existing) return jsonResponse(404, { ok: false, error: "record_not_found", entity, id });
    const archived = { ...existing, archived: true, archived_at: new Date().toISOString(), updated_at: new Date().toISOString() };
    await writeRecord(supabaseUrl, serviceKey, entity, id, archived);
    return jsonResponse(200, { ok: true, entity, record: archived });
  }

  if (action === "upsert") {
    const supplied = body.record && typeof body.record === "object" && !Array.isArray(body.record)
      ? body.record as Row
      : {};
    if (!Object.keys(supplied).length) return jsonResponse(422, { ok: false, error: "record_required" });

    const source = text(supplied.source || "commandcore");
    const externalId = text(supplied.external_id);
    const candidateId = text(supplied.id) || (externalId ? deterministicImportId(entity, source, externalId) : "");
    const existing = candidateId ? await readRecord(supabaseUrl, serviceKey, entity, candidateId) : null;
    const record = normalizeRecord(entity, supplied, existing);
    const id = text(record.id);
    await writeRecord(supabaseUrl, serviceKey, entity, id, record);
    return jsonResponse(200, {
      ok: true,
      entity,
      created: !existing,
      record,
      destructive_delete_used: false,
      external_action_started: false,
    });
  }

  return jsonResponse(422, { ok: false, error: "unsupported_action" });
});
