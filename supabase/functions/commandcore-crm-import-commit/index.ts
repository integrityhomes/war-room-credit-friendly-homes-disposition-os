const SERVICE_VERSION = "2026-08-29.2";
const MAX_BODY_BYTES = 512 * 1024;
const MAX_ROWS = 1000;
const PREVIEW_CHUNK_SIZE = 250;

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

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let i = 0; i < left.length; i += 1) difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return difference === 0;
}

function isAuthenticated(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const auth = req.headers.get("authorization") || "";
  const supplied = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

async function callService(supabaseUrl: string, serviceKey: string, service: string, payload: Row): Promise<Row> {
  const response = await fetch(`${supabaseUrl}/functions/v1/${service}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = parsed && typeof parsed === "object" ? text((parsed as Row).error) : "";
    throw new Error(error || `${service}_failed_${response.status}`);
  }
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : {};
}

function identity(row: Row): string {
  return text(row.identity_key || row.external_id || row.id || row.source_row_id).toLowerCase();
}

function entityOf(row: Row): string {
  const value = text(row.entity || row.entity_type).toLowerCase();
  return ["contacts", "properties", "deals"].includes(value) ? value : "";
}

function recordFor(row: Row): Row {
  const record = row.record && typeof row.record === "object" && !Array.isArray(row.record)
    ? { ...(row.record as Row) }
    : { ...row };
  delete record.approved;
  delete record.record;
  return record;
}

function linksFor(row: Row, ids: Map<string, string>): Row {
  const links: Row = row.links && typeof row.links === "object" && !Array.isArray(row.links)
    ? { ...(row.links as Row) }
    : {};
  const sellerKey = text(row.seller_identity_key || row.contact_identity_key).toLowerCase();
  const propertyKey = text(row.property_identity_key).toLowerCase();
  const dealKey = text(row.deal_identity_key).toLowerCase();
  if (sellerKey && ids.has(`contacts:${sellerKey}`)) links.contact_id = ids.get(`contacts:${sellerKey}`);
  if (propertyKey && ids.has(`properties:${propertyKey}`)) links.property_id = ids.get(`properties:${propertyKey}`);
  if (dealKey && ids.has(`deals:${dealKey}`)) links.deal_id = ids.get(`deals:${dealKey}`);
  return links;
}

async function previewApprovedRows(
  supabaseUrl: string,
  serviceKey: string,
  approved: Row[],
): Promise<Row> {
  const byEntity = new Map<string, Row[]>();
  for (const row of approved) {
    const entity = entityOf(row);
    if (!entity) continue;
    byEntity.set(entity, [...(byEntity.get(entity) || []), recordFor(row)]);
  }

  const entities: Record<string, Row> = {};
  let wouldCreate = 0;
  let wouldUpdate = 0;
  let invalid = 0;
  let duplicates = 0;

  for (const [entity, records] of byEntity.entries()) {
    let entityCreate = 0;
    let entityUpdate = 0;
    let entityInvalid = 0;
    let entityDuplicates = 0;
    for (let offset = 0; offset < records.length; offset += PREVIEW_CHUNK_SIZE) {
      const chunk = records.slice(offset, offset + PREVIEW_CHUNK_SIZE);
      const preview = await callService(supabaseUrl, serviceKey, "commandcore-crm-core", {
        action: "migration_preview",
        entity,
        records: chunk,
      });
      entityCreate += Number(preview.would_create || 0);
      entityUpdate += Number(preview.would_update || 0);
      entityInvalid += Number(preview.invalid_count || 0);
      entityDuplicates += Number(preview.duplicate_count || 0);
    }
    entities[entity] = {
      rows: records.length,
      would_create: entityCreate,
      would_update: entityUpdate,
      invalid_count: entityInvalid,
      duplicate_count: entityDuplicates,
    };
    wouldCreate += entityCreate;
    wouldUpdate += entityUpdate;
    invalid += entityInvalid;
    duplicates += entityDuplicates;
  }

  return {
    live_preview_ok: true,
    entities,
    would_create: wouldCreate,
    would_update: wouldUpdate,
    invalid_count: invalid,
    duplicate_count: duplicates,
    records_written: 0,
    source_records_modified: false,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-crm-import-commit",
      version: SERVICE_VERSION,
      status: "healthy",
      approved_rows_only: true,
      deterministic_upsert: true,
      cross_record_linking: true,
      live_migration_preview_enabled: true,
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

  const rows = Array.isArray(body.rows)
    ? body.rows.filter((item) => item && typeof item === "object") as Row[]
    : [];
  if (!rows.length) return jsonResponse(422, { ok: false, error: "rows_required" });
  if (rows.length > MAX_ROWS) return jsonResponse(422, { ok: false, error: "too_many_rows", max_rows: MAX_ROWS });

  const approved = rows.filter((row) => row.approved === true && entityOf(row));
  const rejected = rows.filter((row) => row.approved !== true || !entityOf(row));
  const apply = body.apply === true;

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  if (!apply) {
    try {
      const livePreview = await previewApprovedRows(supabaseUrl, serviceKey, approved);
      return jsonResponse(200, {
        ok: true,
        apply_requested: false,
        approved_rows: approved.length,
        rejected_rows: rejected.length,
        ready_to_commit: approved.length,
        ...livePreview,
        destructive_delete_used: false,
        external_action_started: false,
      });
    } catch (error) {
      return jsonResponse(503, {
        ok: false,
        apply_requested: false,
        approved_rows: approved.length,
        rejected_rows: rejected.length,
        error: error instanceof Error ? error.message : "live_migration_preview_failed",
        records_written: 0,
        source_records_modified: false,
        destructive_delete_used: false,
        external_action_started: false,
      });
    }
  }

  const ordered = [...approved].sort((a, b) => {
    const order: Record<string, number> = { contacts: 0, properties: 1, deals: 2 };
    return order[entityOf(a)] - order[entityOf(b)];
  });
  const ids = new Map<string, string>();
  const committed: Row[] = [];
  const failed: Row[] = [];

  for (const row of ordered) {
    const entity = entityOf(row);
    const record = recordFor(row);
    record.links = linksFor(row, ids);
    try {
      const result = await callService(supabaseUrl, serviceKey, "commandcore-crm-core", {
        action: "upsert",
        entity,
        record,
      });
      const saved = result.record && typeof result.record === "object" && !Array.isArray(result.record)
        ? result.record as Row
        : {};
      const id = text(saved.id);
      const key = identity(row);
      if (id && key) ids.set(`${entity}:${key}`, id);
      committed.push({ entity, id, created: result.created === true, source: saved.source, external_id: saved.external_id });
    } catch (error) {
      failed.push({ entity, identity_key: identity(row), error: error instanceof Error ? error.message : "commit_failed" });
    }
  }

  return jsonResponse(200, {
    ok: failed.length === 0,
    apply_requested: true,
    approved_rows: approved.length,
    rejected_rows: rejected.length,
    committed_count: committed.length,
    failed_count: failed.length,
    committed,
    failed,
    destructive_delete_used: false,
    external_action_started: false,
  });
});
