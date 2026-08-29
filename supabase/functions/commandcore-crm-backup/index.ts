const SERVICE_VERSION = "2026-08-29.1";
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

async function ensurePrivateBackupBucket(
  supabaseUrl: string,
  serviceRoleKey: string,
): Promise<void> {
  const headers = storageHeaders(serviceRoleKey);
  const listed = await fetch(`${supabaseUrl}/storage/v1/bucket`, { headers });
  if (!listed.ok) throw new Error(`backup_bucket_list_failed_${listed.status}`);
  const buckets = await listed.json() as Row[];
  const existing = buckets.find((bucket) =>
    String(bucket.id || bucket.name || "").trim() === BACKUP_BUCKET
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

async function listSourceObjects(
  supabaseUrl: string,
  serviceRoleKey: string,
  entity: string,
): Promise<string[]> {
  const headers = storageHeaders(serviceRoleKey);
  const paths: string[] = [];
  let offset = 0;

  while (offset < MAX_OBJECTS_PER_ENTITY) {
    const response = await fetch(
      `${supabaseUrl}/storage/v1/object/list/${SOURCE_BUCKET}`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          prefix: entity,
          limit: PAGE_SIZE,
          offset,
          sortBy: { column: "name", order: "asc" },
        }),
      },
    );
    if (!response.ok) {
      throw new Error(`source_list_failed_${entity}_${response.status}`);
    }
    const rows = await response.json() as Row[];
    for (const row of rows) {
      const name = String(row.name || "").trim();
      if (name.endsWith(".json")) paths.push(`${entity}/${name}`);
    }
    if (rows.length < PAGE_SIZE) break;
    offset += PAGE_SIZE;
  }

  if (offset >= MAX_OBJECTS_PER_ENTITY) {
    throw new Error(`source_object_limit_exceeded_${entity}`);
  }
  return paths;
}

async function readSourceObject(
  supabaseUrl: string,
  serviceRoleKey: string,
  sourcePath: string,
): Promise<string> {
  const response = await fetch(
    `${supabaseUrl}/storage/v1/object/authenticated/${SOURCE_BUCKET}/${sourcePath}`,
    {
      headers: {
        authorization: `Bearer ${serviceRoleKey}`,
        apikey: serviceRoleKey,
      },
    },
  );
  if (!response.ok) {
    throw new Error(`source_read_failed_${response.status}`);
  }
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
  if (!response.ok) {
    throw new Error(`backup_write_failed_${response.status}`);
  }
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

  const createdAt = new Date();
  const id = snapshotId(createdAt);
  const counts: Record<string, number> = {};
  let copiedCount = 0;

  try {
    await ensurePrivateBackupBucket(supabaseUrl, serviceRoleKey);

    for (const entity of ENTITY_TYPES) {
      const paths = await listSourceObjects(supabaseUrl, serviceRoleKey, entity);
      counts[entity] = paths.length;
      for (const sourcePath of paths) {
        const content = await readSourceObject(
          supabaseUrl,
          serviceRoleKey,
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

    return jsonResponse(200, {
      ok: true,
      snapshot_id: id,
      object_count: copiedCount,
      entity_counts: counts,
      source_records_modified: false,
      destructive_action_started: false,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore CRM backup failed", error);
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "crm_backup_unavailable",
      snapshot_id: id,
      copied_count_before_failure: copiedCount,
      source_records_modified: false,
      destructive_action_started: false,
      external_action_started: false,
    });
  }
});
