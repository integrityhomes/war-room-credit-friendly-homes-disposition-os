const SERVICE_VERSION = "2026-08-29.1";
const CRM_BUCKET = "commandcore-crm-core";
const RECONCILIATION_BUCKET = "commandcore-crm-reconciliation";
const LIST_PAGE_SIZE = 1000;
const MAX_BODY_BYTES = 256 * 1024;

const ENTITY_TYPES = [
  "contacts",
  "properties",
  "deals",
  "activities",
  "communications",
  "tasks",
  "offers",
  "documents",
  "transactions",
] as const;

type EntityType = typeof ENTITY_TYPES[number];
type Row = Record<string, unknown>;

type EntityManifest = {
  count: number;
  external_id_sha256: string;
};

type SourceManifest = {
  source_system: string;
  generated_at?: string;
  real_source_export?: boolean;
  entities: Partial<Record<EntityType, EntityManifest>>;
};

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function text(value: unknown): string {
  return String(value ?? "").trim();
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

function normalizeSource(value: unknown): string {
  return text(value).toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
}

function syntheticSource(source: string): boolean {
  return source.startsWith("deployment-canary") || source.startsWith("synthetic") || source.startsWith("test-") || source === "test";
}

function validHash(value: unknown): string {
  const candidate = text(value).toLowerCase();
  return /^[a-f0-9]{64}$/.test(candidate) ? candidate : "";
}

async function sha256(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function hashExternalIds(ids: string[]): Promise<string> {
  const normalized = [...new Set(ids.map((id) => text(id).toLowerCase()).filter(Boolean))].sort();
  return await sha256(normalized.join("\n"));
}

async function listObjects(
  supabaseUrl: string,
  serviceKey: string,
  bucket: string,
  prefix: string,
): Promise<Row[]> {
  const objects: Row[] = [];
  for (let offset = 0; ; offset += LIST_PAGE_SIZE) {
    const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${bucket}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${serviceKey}`,
        apikey: serviceKey,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        prefix,
        limit: LIST_PAGE_SIZE,
        offset,
        sortBy: { column: "name", order: "asc" },
      }),
    });
    if (response.status === 400 || response.status === 404) return [];
    if (!response.ok) throw new Error(`storage_list_failed_${response.status}`);
    const page = await response.json() as Row[];
    objects.push(...page);
    if (page.length < LIST_PAGE_SIZE) break;
  }
  return objects;
}

async function readJsonObject(
  supabaseUrl: string,
  serviceKey: string,
  bucket: string,
  path: string,
): Promise<Row | null> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/authenticated/${bucket}/${path}`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (response.status === 400 || response.status === 404) return null;
  if (!response.ok) throw new Error(`storage_read_failed_${response.status}`);
  const parsed = await response.json().catch(() => null);
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : null;
}

async function targetManifest(
  supabaseUrl: string,
  serviceKey: string,
  sourceSystem: string,
): Promise<Record<EntityType, EntityManifest>> {
  const output = {} as Record<EntityType, EntityManifest>;
  for (const entity of ENTITY_TYPES) {
    const objects = await listObjects(supabaseUrl, serviceKey, CRM_BUCKET, entity);
    const externalIds: string[] = [];
    for (const object of objects) {
      const name = text(object.name);
      if (!name.endsWith(".json")) continue;
      const record = await readJsonObject(supabaseUrl, serviceKey, CRM_BUCKET, `${entity}/${name}`);
      if (!record) continue;
      if (normalizeSource(record.source) !== sourceSystem) continue;
      const externalId = text(record.external_id);
      if (externalId) externalIds.push(externalId);
    }
    output[entity] = {
      count: externalIds.length,
      external_id_sha256: await hashExternalIds(externalIds),
    };
  }
  return output;
}

function parseSourceManifest(value: unknown): SourceManifest | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const row = value as Row;
  const sourceSystem = normalizeSource(row.source_system);
  const entitiesRaw = row.entities;
  if (!sourceSystem || !entitiesRaw || typeof entitiesRaw !== "object" || Array.isArray(entitiesRaw)) return null;
  const entities: Partial<Record<EntityType, EntityManifest>> = {};
  for (const entity of ENTITY_TYPES) {
    const raw = (entitiesRaw as Row)[entity];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const rawRow = raw as Row;
    const count = Number(rawRow.count);
    const hash = validHash(rawRow.external_id_sha256);
    if (!Number.isInteger(count) || count < 0 || !hash) return null;
    entities[entity] = { count, external_id_sha256: hash };
  }
  if (Object.keys(entities).length !== ENTITY_TYPES.length) return null;
  return {
    source_system: sourceSystem,
    generated_at: text(row.generated_at) || undefined,
    real_source_export: row.real_source_export === true,
    entities,
  };
}

function compareManifests(
  source: SourceManifest,
  target: Record<EntityType, EntityManifest>,
): { entities: Row; exact_match: boolean; mismatched_entities: string[] } {
  const entities: Row = {};
  const mismatched: string[] = [];
  for (const entity of ENTITY_TYPES) {
    const sourceEntity = source.entities[entity] as EntityManifest;
    const targetEntity = target[entity];
    const countMatch = sourceEntity.count === targetEntity.count;
    const hashMatch = constantTimeEqual(sourceEntity.external_id_sha256, targetEntity.external_id_sha256);
    const exact = countMatch && hashMatch;
    if (!exact) mismatched.push(entity);
    entities[entity] = {
      source_count: sourceEntity.count,
      commandcore_count: targetEntity.count,
      count_match: countMatch,
      external_id_hash_match: hashMatch,
      exact_match: exact,
    };
  }
  return { entities, exact_match: mismatched.length === 0, mismatched_entities: mismatched };
}

async function ensurePrivateBucket(supabaseUrl: string, serviceKey: string): Promise<void> {
  const response = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!response.ok) throw new Error("bucket_list_failed");
  const buckets = await response.json() as Row[];
  const existing = buckets.find((bucket) => text(bucket.id || bucket.name) === RECONCILIATION_BUCKET);
  if (existing) {
    if (existing.public === true) throw new Error("reconciliation_bucket_must_be_private");
    return;
  }
  const created = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ id: RECONCILIATION_BUCKET, name: RECONCILIATION_BUCKET, public: false }),
  });
  if (!created.ok && created.status !== 409) throw new Error("bucket_create_failed");
}

async function writeVerification(
  supabaseUrl: string,
  serviceKey: string,
  source: SourceManifest,
  comparison: { entities: Row; exact_match: boolean; mismatched_entities: string[] },
): Promise<string> {
  await ensurePrivateBucket(supabaseUrl, serviceKey);
  const verifiedAt = new Date().toISOString();
  const id = `${verifiedAt.replace(/[:.]/g, "-")}-${source.source_system}`;
  const record = {
    verification_id: id,
    verified_at: verifiedAt,
    source_system: source.source_system,
    source_manifest_generated_at: source.generated_at || null,
    exact_match: comparison.exact_match,
    entity_count: ENTITY_TYPES.length,
    mismatched_entities: comparison.mismatched_entities,
    comparison: comparison.entities,
    source_manifest_contains_raw_records: false,
    external_execution_started: false,
    destructive_action_started: false,
  };
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${RECONCILIATION_BUCKET}/verified/${id}.json`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "false",
    },
    body: JSON.stringify(record),
  });
  if (!response.ok) throw new Error(`verification_write_failed_${response.status}`);
  return id;
}

async function latestVerification(supabaseUrl: string, serviceKey: string): Promise<Row | null> {
  const rows = await listObjects(supabaseUrl, serviceKey, RECONCILIATION_BUCKET, "verified");
  const names = rows.map((row) => text(row.name)).filter((name) => name.endsWith(".json")).sort().reverse();
  if (!names.length) return null;
  return await readJsonObject(supabaseUrl, serviceKey, RECONCILIATION_BUCKET, `verified/${names[0]}`);
}

Deno.serve(async (req) => {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";

  if (req.method === "GET") {
    let latest: Row | null = null;
    if (supabaseUrl && serviceKey) {
      try {
        latest = await latestVerification(supabaseUrl, serviceKey);
      } catch {
        latest = null;
      }
    }
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-crm-reconciliation",
      version: SERVICE_VERSION,
      status: "healthy",
      supported_entities: [...ENTITY_TYPES],
      reconciliation_verified: latest?.exact_match === true,
      latest_verification_id: latest ? text(latest.verification_id) || null : null,
      latest_verified_at: latest ? text(latest.verified_at) || null : null,
      source_system: latest ? text(latest.source_system) || null : null,
      synthetic_canaries_can_verify: false,
      owner_confirmation_required_to_record_verification: true,
      raw_source_records_required: false,
      destructive_delete_enabled: false,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

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

  const action = text(body.action || "preview").toLowerCase();
  const source = parseSourceManifest(body.source_manifest);
  if (!source) {
    return jsonResponse(422, {
      ok: false,
      error: "complete_source_manifest_required",
      required_entities: [...ENTITY_TYPES],
      required_fields_per_entity: ["count", "external_id_sha256"],
    });
  }

  const target = await targetManifest(supabaseUrl, serviceKey, source.source_system);
  const comparison = compareManifests(source, target);

  if (action === "preview") {
    return jsonResponse(200, {
      ok: true,
      action: "preview",
      source_system: source.source_system,
      real_source_export_declared: source.real_source_export === true,
      exact_match: comparison.exact_match,
      mismatched_entities: comparison.mismatched_entities,
      entities: comparison.entities,
      eligible_for_owner_verification:
        comparison.exact_match && source.real_source_export === true && !syntheticSource(source.source_system),
      reconciliation_verified: false,
      verification_record_written: false,
      source_records_modified: false,
      commandcore_records_modified: false,
      destructive_action_started: false,
      external_action_started: false,
    });
  }

  if (action === "record_verified") {
    if (body.owner_approved !== true || text(body.confirmation_phrase) !== "VERIFY CRM RECONCILIATION") {
      return jsonResponse(409, {
        ok: false,
        error: "explicit_owner_reconciliation_approval_required",
        reconciliation_verified: false,
        verification_record_written: false,
      });
    }
    if (!source.real_source_export || syntheticSource(source.source_system)) {
      return jsonResponse(409, {
        ok: false,
        error: "real_source_export_required",
        reconciliation_verified: false,
        verification_record_written: false,
      });
    }
    if (!comparison.exact_match) {
      return jsonResponse(409, {
        ok: false,
        error: "source_and_commandcore_do_not_match",
        mismatched_entities: comparison.mismatched_entities,
        reconciliation_verified: false,
        verification_record_written: false,
      });
    }
    const verificationId = await writeVerification(supabaseUrl, serviceKey, source, comparison);
    return jsonResponse(200, {
      ok: true,
      action: "record_verified",
      reconciliation_verified: true,
      verification_record_written: true,
      verification_id: verificationId,
      source_system: source.source_system,
      source_records_modified: false,
      commandcore_records_modified: false,
      destructive_action_started: false,
      external_action_started: false,
    });
  }

  return jsonResponse(422, { ok: false, error: "unsupported_action" });
});
