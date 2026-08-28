const SERVICE_VERSION = "2026-08-28.2";
const MAX_BODY_BYTES = 64 * 1024;
const BUCKET = "commandcore-coverage-exceptions";

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
  for (let i = 0; i < left.length; i += 1) difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
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

function safeKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
}

async function writeException(supabaseUrl: string, serviceKey: string, record: RecordValue): Promise<void> {
  const exceptionId = text(record.exception_id) || crypto.randomUUID();
  const createdAt = text(record.created_at) || new Date().toISOString();
  const day = createdAt.slice(0, 10);
  const ownerId = safeKey(text(record.owner_id));
  const path = `${day}/${ownerId}/${safeKey(exceptionId)}.json`;
  const body = { ...record, exception_id: exceptionId, created_at: createdAt };
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "true",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`exception_write_failed_${response.status}`);
}

async function listPrefix(supabaseUrl: string, serviceKey: string, prefix: string): Promise<RecordValue[]> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix, limit: 1000, offset: 0, sortBy: { column: "name", order: "asc" } }),
  });
  if (!response.ok) throw new Error(`exception_list_failed_${response.status}`);
  const parsed = await response.json();
  return Array.isArray(parsed) ? parsed.filter((item) => item && typeof item === "object") as RecordValue[] : [];
}

async function readException(supabaseUrl: string, serviceKey: string, path: string): Promise<RecordValue | null> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/${path}`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!response.ok) return null;
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as RecordValue : null;
}

function dayKeys(days: number): string[] {
  const keys: string[] = [];
  const now = new Date();
  for (let offset = 0; offset < days; offset += 1) {
    const day = new Date(now.getTime() - offset * 86_400_000);
    keys.push(day.toISOString().slice(0, 10));
  }
  return keys;
}

async function listExceptions(
  supabaseUrl: string,
  serviceKey: string,
  days: number,
  statusFilter: string,
): Promise<RecordValue[]> {
  const results: RecordValue[] = [];
  for (const day of dayKeys(days)) {
    let owners: RecordValue[] = [];
    try {
      owners = await listPrefix(supabaseUrl, serviceKey, day);
    } catch {
      continue;
    }
    for (const owner of owners) {
      const ownerName = text(owner.name);
      if (!ownerName) continue;
      let files: RecordValue[] = [];
      try {
        files = await listPrefix(supabaseUrl, serviceKey, `${day}/${ownerName}`);
      } catch {
        continue;
      }
      for (const file of files) {
        const fileName = text(file.name);
        if (!fileName.endsWith(".json")) continue;
        const record = await readException(supabaseUrl, serviceKey, `${day}/${ownerName}/${fileName}`);
        if (!record) continue;
        const status = text(record.status || "open").toLowerCase();
        if (statusFilter && statusFilter !== "all" && status !== statusFilter) continue;
        results.push(record);
      }
    }
  }
  return results.sort((a, b) => text(b.created_at).localeCompare(text(a.created_at)));
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-coverage-exception-ledger",
      version: SERVICE_VERSION,
      status: "healthy",
      internal_audit_only: true,
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

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const action = text(body.action || "write").toLowerCase();
  if (action === "list") {
    const requestedDays = Number(body.days ?? 14);
    const days = Number.isFinite(requestedDays) ? Math.min(Math.max(Math.floor(requestedDays), 1), 60) : 14;
    const statusFilter = text(body.status || "open").toLowerCase();
    const exceptions = await listExceptions(supabaseUrl, serviceKey, days, statusFilter);
    return jsonResponse(200, {
      ok: true,
      days,
      status_filter: statusFilter,
      exception_count: exceptions.length,
      critical_count: exceptions.filter((item) => text(item.severity).toLowerCase() === "critical").length,
      warning_count: exceptions.filter((item) => text(item.severity).toLowerCase() === "warning").length,
      exceptions,
      readiness_changed: false,
      approval_changed: false,
      consent_changed: false,
      external_action_started: false,
    });
  }

  const records = Array.isArray(body.exceptions)
    ? body.exceptions.filter((item) => item && typeof item === "object") as RecordValue[]
    : body.exception && typeof body.exception === "object" && !Array.isArray(body.exception)
    ? [body.exception as RecordValue]
    : [];
  if (!records.length) return jsonResponse(422, { ok: false, error: "exception_required" });

  let written = 0;
  const failed: RecordValue[] = [];
  for (const record of records) {
    try {
      await writeException(supabaseUrl, serviceKey, {
        ...record,
        severity: text(record.severity || "warning").toLowerCase(),
        source: text(record.source || "commandcore-scheduled-coverage"),
        status: text(record.status || "open").toLowerCase(),
      });
      written += 1;
    } catch (error) {
      failed.push({ exception_id: text(record.exception_id), error: String(error) });
    }
  }

  return jsonResponse(failed.length ? 207 : 200, {
    ok: failed.length === 0,
    written,
    failed,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    legal_terms_changed: false,
    payment_started: false,
    external_action_started: false,
  });
});
