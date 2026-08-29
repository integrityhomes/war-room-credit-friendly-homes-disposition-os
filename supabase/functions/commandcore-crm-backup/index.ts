const SERVICE_VERSION = "2026-08-29.2";
const SOURCE_BUCKET = "commandcore-crm-core";
const BACKUP_BUCKET = "commandcore-crm-backups";
const PAGE_SIZE = 100;
const MAX_OBJECTS_PER_ENTITY = 10000;

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

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
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

function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const authorization = req.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ")
    ? authorization.slice(7).trim()
    : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function storageHeaders(serviceRoleKey: string): HeadersInit {
  return {
    authorization: `Bearer ${serviceRoleKey}`,
    apikey: serviceRoleKey,
    "content-type": "application/json",
  };
}

function snapshotId(now = new Date()): string {
  return now.toISOString().replace(/[:.]/g, "-");
}

function safeSnapshotId(value: unknown): string {
  const supplied = text(value);
  return /^[0-9TZ-]{20,40}$/.test(supplied) ? supplied : "";
}

async function ensurePrivateBackupBucket(
  supabaseUrl: string,
  serviceRoleKey: string,
): Promise<void> {
  const headers = storageHeaders(serviceRoleKey);
  const listed = await fetch(`${supabaseUrl}/storage/v1/bucket`, { headers });
  if (!listed.ok) throw new Error(`backup_bucket_list_failed_${listed.status}`);
  const buckets = await listed.json() as Row[];
  const existing = buckets.find((bucket) =>
    text(bucket.id || bucket.name) === BACKUP_BUCKET
  );
  if (existing) {
    if (existing.public === true) throw new Error("backup_bucket_must_be_private");
    return;
  }

  const created = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      id: BACKUP_BUCKET,
      name: BACKUP_BUCKET,
      public: false,
    }),
  });
  if (!created.ok && created.status !== 409) {
    throw new Error(`backup_bucket_create_failed_${created.status}`);
  }
}

async function listObjects(
  supabaseUrl: string,
  serviceRoleKey: string,
  bucket: string,
  prefix: string,
  maxObjects = MAX_OBJECTS_PER_ENTITY,
): Promise<Row[]> {
  const headers = storageHeaders(serviceRoleKey);
  const rows: Row[] = [];
  let offset = 0;

  while (offset < maxObjects) {
    const response = await fetch(
      `${supabaseUrl}/storage/v1/object/list/${bucket}`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          prefix,
          limit: PAGE_SIZE,
          offset,
          sortBy: { column: "name", order: "asc" },
        }),
      },
    );
    if (!response.ok) {
      throw new Error(`object_list_failed_${bucket}_${response.status}`);
    }
    const page = await response.json() as Row[];
    rows.push(...page);
    if (page.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }

  if (offset >= maxObjects) throw new Error(`object_limit_exceeded_${prefix}`);
  return rows;
}

async function listSourceObjects(
  supabaseUrl: string,
  serviceRoleKey: string,
  entity: string,
): Promise<string[]> {
  const rows = await listObjects(
    supabaseUrl,
    serviceRoleKey,
    SOURCE_BUCKET,
    entity,
  );
  return rows
    .map((row) => text(row.name))
    .filter((name) => name.endsWith(".json"))
    .map((name) => `${entity}/${name}`);
}

async function readObject(
  supabaseUrl: string,
  serviceRoleKey: string,
  bucket: string,
  objectPath: string,
): Promise<string> {
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/authenticated/${bucket}/${objectPath}`,
    {
      headers: {
        authorization: `Bearer ${serviceRoleKey}`,
        apikey: serviceRoleKey,
      },
    },
  );
  if (!response.ok) throw new Error(`object_read_failed_${bucket}_${response.status}`);
  return await response.text();
}

async function writeBackupObject(
  supabaseUrl: string,
  serviceRoleKey: string,
  destinationPath: string,
  content: string,
): Promise<void> {
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/${BACKUP_BUCKET}/${destinationPath}`,
    {
      method: "POST",
      headers: {
        ...storageHeaders(serviceRoleKey),
        "x-upsert": "false",
      },
      body: content,
    },
  );
  if (!response.ok) throw new Error(`backup_write_failed_${response.status}`);
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function readManifest(
  supabaseUrl: string,
  serviceRoleKey: string,
  id: string,
): Promise<Row> {
  const raw = await readObject(
    supabaseUrl,
    serviceRoleKey,
    BACKUP_BUCKET,
    `snapshots/${id}/manifest.json`,
  );
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("snapshot_manifest_invalid");
  }
  return parsed as Row;
}

async function listSnapshots(
  supabaseUrl: string,
  serviceRoleKey: string,
): Promise<Row[]> {
  const rows = await listObjects(
    supabaseUrl,
    serviceRoleKey,
    BACKUP_BUCKET,
    "snapshots",
    5000,
  );
  const ids = [...new Set(
    rows
      .map((row) => safeSnapshotId(row.name))
      .filter(Boolean),
  )].sort().reverse();
  const snapshots: Row[] = [];
  for (const id of ids.slice(0, 100)) {
    try {
      const manifest = await readManifest(supabaseUrl, serviceRoleKey, id);
      snapshots.push({
        snapshot_id: id,
        created_at: manifest.created_at || null,
        object_count: manifest.object_count ?? null,
        entity_counts: manifest.entity_counts || {},
        manifest_valid: true,
      });
    } catch {
      snapshots.push({
        snapshot_id: id,
        created_at: null,
        object_count: null,
        entity_counts: {},
        manifest_valid: false,
      });
    }
  }
  return snapshots;
}

async function previewRestore(
  supabaseUrl: string,
  serviceRoleKey: string,
  id: string,
): Promise<Row> {
  const manifest = await readManifest(supabaseUrl, serviceRoleKey, id);
  const manifestCounts = manifest.entity_counts &&
      typeof manifest.entity_counts === "object" &&
      !Array.isArray(manifest.entity_counts)
    ? manifest.entity_counts as Row
    : {};
  const byEntity: Record<string, Row> = {};
  let wouldCreate = 0;
  let wouldOverwrite = 0;
  let unchanged = 0;
  let liveOnly = 0;
  let snapshotObjects = 0;
  let manifestMatches = true;

  for (const entity of ENTITY_TYPES) {
    const backupRows = await listObjects(
      supabaseUrl,
      serviceRoleKey,
      BACKUP_BUCKET,
      `snapshots/${id}/${entity}`,
    );
    const backupNames = backupRows
      .map((row) => text(row.name))
      .filter((name) => name.endsWith(".json"));
    const livePaths = await listSourceObjects(supabaseUrl, serviceRoleKey, entity);
    const liveNames = livePaths.map((path) => path.slice(entity.length + 1));
    const liveSet = new Set(liveNames);
    const backupSet = new Set(backupNames);
    let entityCreate = 0;
    let entityOverwrite = 0;
    let entityUnchanged = 0;

    for (const name of backupNames) {
      if (!liveSet.has(name)) {
        entityCreate += 1;
        continue;
      }
      const backupRaw = await readObject(
        supabaseUrl,
        serviceRoleKey,
        BACKUP_BUCKET,
        `snapshots/${id}/${entity}/${name}`,
      );
      const liveRaw = await readObject(
        supabaseUrl,
        serviceRoleKey,
        SOURCE_BUCKET,
        `${entity}/${name}`,
      );
      if (await sha256(backupRaw) === await sha256(liveRaw)) {
        entityUnchanged += 1;
      } else {
        entityOverwrite += 1;
      }
    }

    const entityLiveOnly = liveNames.filter((name) => !backupSet.has(name)).length;
    const expected = Number(manifestCounts[entity] ?? backupNames.length);
    const entityManifestMatches = Number.isFinite(expected) && expected === backupNames.length;
    if (!entityManifestMatches) manifestMatches = false;

    snapshotObjects += backupNames.length;
    wouldCreate += entityCreate;
    wouldOverwrite += entityOverwrite;
    unchanged += entityUnchanged;
    liveOnly += entityLiveOnly;
    byEntity[entity] = {
      snapshot_count: backupNames.length,
      live_count: liveNames.length,
      unchanged: entityUnchanged,
      would_create: entityCreate,
      would_overwrite: entityOverwrite,
      live_only_untouched: entityLiveOnly,
      manifest_count_matches: entityManifestMatches,
    };
  }

  const expectedObjectCount = Number(manifest.object_count ?? snapshotObjects);
  const objectCountMatches = Number.isFinite(expectedObjectCount) &&
    expectedObjectCount === snapshotObjects;
  manifestMatches = manifestMatches && objectCountMatches;

  return {
    snapshot_id: id,
    snapshot_objects: snapshotObjects,
    manifest_valid: manifestMatches,
    manifest_object_count_matches: objectCountMatches,
    would_create: wouldCreate,
    would_overwrite: wouldOverwrite,
    unchanged,
    live_only_untouched: liveOnly,
    by_entity: byEntity,
    restore_enabled: false,
    restore_executed: false,
    source_records_modified: false,
    destructive_action_started: false,
    external_action_started: false,
  };
}

async function createSnapshot(
  supabaseUrl: string,
  serviceRoleKey: string,
): Promise<Row> {
  const createdAt = new Date();
  const id = snapshotId(createdAt);
  const counts: Record<string, number> = {};
  let copiedCount = 0;

  for (const entity of ENTITY_TYPES) {
    const paths = await listSourceObjects(supabaseUrl, serviceRoleKey, entity);
    counts[entity] = paths.length;
    for (const sourcePath of paths) {
      const content = await readObject(
        supabaseUrl,
        serviceRoleKey,
        SOURCE_BUCKET,
        sourcePath,
      );
      await writeBackupObject(
        supabaseUrl,
        serviceRoleKey,
        `snapshots/${id}/${sourcePath}`,
        content,
      );
      copiedCount += 1;
    }
  }

  const manifest = {
    snapshot_id: id,
    created_at: createdAt.toISOString(),
    source_bucket: SOURCE_BUCKET,
    backup_bucket: BACKUP_BUCKET,
    entity_counts: counts,
    object_count: copiedCount,
    private_backup_required: true,
    source_records_modified: false,
    destructive_cleanup_enabled: false,
  };
  await writeBackupObject(
    supabaseUrl,
    serviceRoleKey,
    `snapshots/${id}/manifest.json`,
    JSON.stringify(manifest, null, 2),
  );

  return {
    snapshot_id: id,
    object_count: copiedCount,
    entity_counts: counts,
    source_records_modified: false,
    destructive_action_started: false,
    external_action_started: false,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-crm-backup",
      version: SERVICE_VERSION,
      status: "healthy",
      source_bucket: SOURCE_BUCKET,
      backup_bucket: BACKUP_BUCKET,
      backup_bucket_private_required: true,
      snapshot_inventory_enabled: true,
      restore_preview_enabled: true,
      restore_enabled: false,
      destructive_cleanup_enabled: false,
      external_execution_enabled: false,
    });
  }

  if (req.method !== "POST") {
    return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  }
  if (!authed(req)) {
    return jsonResponse(401, { ok: false, error: "unauthorized" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) {
    return jsonResponse(500, { ok: false, error: "service_not_configured" });
  }

  let body: Row = {};
  try {
    body = await req.json();
  } catch {
    body = {};
  }
  const action = text(body.action || "create_snapshot").toLowerCase();

  try {
    await ensurePrivateBackupBucket(supabaseUrl, serviceRoleKey);

    if (action === "list_snapshots") {
      const snapshots = await listSnapshots(supabaseUrl, serviceRoleKey);
      return jsonResponse(200, {
        ok: true,
        action,
        snapshots,
        snapshot_count: snapshots.length,
        restore_enabled: false,
        source_records_modified: false,
        destructive_action_started: false,
        external_action_started: false,
      });
    }

    if (action === "preview_restore") {
      const id = safeSnapshotId(body.snapshot_id);
      if (!id) return jsonResponse(422, { ok: false, error: "valid_snapshot_id_required" });
      const preview = await previewRestore(supabaseUrl, serviceRoleKey, id);
      return jsonResponse(200, { ok: true, action, ...preview });
    }

    if (action !== "create_snapshot") {
      return jsonResponse(422, { ok: false, error: "unsupported_action" });
    }

    const snapshot = await createSnapshot(supabaseUrl, serviceRoleKey);
    return jsonResponse(200, { ok: true, action, ...snapshot });
  } catch (error) {
    console.error("CommandCore CRM backup operation failed", error);
    return jsonResponse(503, {
      ok: false,
      action,
      error: error instanceof Error ? error.message : "crm_backup_unavailable",
      restore_enabled: false,
      source_records_modified: false,
      destructive_action_started: false,
      external_action_started: false,
    });
  }
});
