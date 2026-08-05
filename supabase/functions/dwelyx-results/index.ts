import { createClient } from "npm:@supabase/supabase-js@2";

const BUCKET = "cfh-dwelyx-attribution";
const PREFIX = "events";
const MAX_BODY_BYTES = 16 * 1024;
const REPLAY_WINDOW_SECONDS = 300;
const SCHEMA_VERSION = "1.0";

const ALLOWED_EVENT_TYPES = new Set([
  "buyer.registered",
  "buyer.qualified",
  "application.started",
  "application.submitted",
  "showing.requested",
  "showing.scheduled",
  "contract.pending",
  "contract.signed",
  "home.filled",
]);

const PROPERTY_REQUIRED_EVENTS = new Set([
  "application.started",
  "application.submitted",
  "showing.requested",
  "showing.scheduled",
  "contract.pending",
  "contract.signed",
  "home.filled",
]);

const ALLOWED_KEYS = new Set([
  "schema_version",
  "event_id",
  "event_type",
  "occurred_at",
  "dwelyx_buyer_id",
  "dwelyx_property_id",
  "cfh_property_id",
  "source",
  "medium",
  "campaign",
  "dwelyx_record_url",
  "test_mode",
]);

const PROHIBITED_KEYS = new Set([
  "name",
  "first_name",
  "last_name",
  "full_name",
  "email",
  "email_address",
  "phone",
  "phone_number",
  "mobile",
  "address",
  "street_address",
  "date_of_birth",
  "dob",
  "ssn",
  "social_security_number",
  "income",
  "employer",
  "application_data",
  "documents",
  "document_url",
  "credit_score",
  "bank_account",
]);

const SAFE_ID = /^[A-Za-z0-9._:-]+$/;
const encoder = new TextEncoder();

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
}

function findProhibitedKeys(value: unknown, prefix = ""): string[] {
  const violations: string[] = [];
  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      violations.push(...findProhibitedKeys(item, `${prefix}[${index}]`));
    });
    return violations;
  }
  if (value && typeof value === "object") {
    for (const [key, nested] of Object.entries(value as Record<string, unknown>)) {
      const normalized = normalizeKey(key);
      const path = prefix ? `${prefix}.${normalized}` : normalized;
      if (PROHIBITED_KEYS.has(normalized)) violations.push(path);
      violations.push(...findProhibitedKeys(nested, path));
    }
  }
  return violations;
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

async function hmacSignature(body: string, timestamp: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const bytes = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, encoder.encode(`${timestamp}.${body}`)),
  );
  const hex = Array.from(bytes).map((value) => value.toString(16).padStart(2, "0")).join("");
  return `sha256=${hex}`;
}

function validateDwelyxUrl(value: unknown): boolean {
  if (value === undefined || value === null || value === "") return true;
  if (typeof value !== "string") return false;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    return parsed.protocol === "https:" && (host === "dwelyx.com" || host.endsWith(".dwelyx.com"));
  } catch {
    return false;
  }
}

function validatePayload(payload: unknown): string[] {
  const errors: string[] = [];
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return ["Body must be a JSON object"];
  }
  const record = payload as Record<string, unknown>;
  const prohibited = findProhibitedKeys(record);
  if (prohibited.length) errors.push(`Buyer personal information is not allowed: ${prohibited.join(", ")}`);
  for (const key of Object.keys(record)) {
    if (!ALLOWED_KEYS.has(key)) errors.push(`Unexpected field: ${key}`);
  }
  if (record.schema_version !== SCHEMA_VERSION) errors.push("Unsupported schema_version");
  if (typeof record.event_id !== "string" || record.event_id.length < 8 || !SAFE_ID.test(record.event_id)) {
    errors.push("event_id is invalid");
  }
  if (typeof record.event_type !== "string" || !ALLOWED_EVENT_TYPES.has(record.event_type)) {
    errors.push("event_type is invalid");
  }
  if (typeof record.dwelyx_buyer_id !== "string" || record.dwelyx_buyer_id.length < 3 || !SAFE_ID.test(record.dwelyx_buyer_id)) {
    errors.push("dwelyx_buyer_id is invalid");
  }
  for (const key of ["dwelyx_property_id", "cfh_property_id"]) {
    const value = record[key];
    if (value !== undefined && value !== "" && (typeof value !== "string" || !SAFE_ID.test(value))) {
      errors.push(`${key} is invalid`);
    }
  }
  const occurredAt = typeof record.occurred_at === "string" ? Date.parse(record.occurred_at) : Number.NaN;
  if (!Number.isFinite(occurredAt)) errors.push("occurred_at is invalid");
  if (
    typeof record.event_type === "string" &&
    PROPERTY_REQUIRED_EVENTS.has(record.event_type) &&
    !record.dwelyx_property_id &&
    !record.cfh_property_id
  ) {
    errors.push("This event requires a property ID");
  }
  if (!validateDwelyxUrl(record.dwelyx_record_url)) errors.push("dwelyx_record_url must use HTTPS on dwelyx.com");
  if (record.test_mode !== undefined && typeof record.test_mode !== "boolean") errors.push("test_mode must be boolean");
  return errors;
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") return jsonResponse(405, { error: "POST required" });

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const webhookSecret = Deno.env.get("DWELYX_WEBHOOK_SECRET") ?? "";
  if (!supabaseUrl || !serviceRoleKey || !webhookSecret) {
    return jsonResponse(503, { error: "Receiver is not configured" });
  }

  const timestamp = request.headers.get("x-dwelyx-timestamp") ?? "";
  const signature = request.headers.get("x-dwelyx-signature") ?? "";
  const headerEventId = request.headers.get("x-dwelyx-event-id") ?? "";
  if (!timestamp || !signature || !headerEventId) {
    return jsonResponse(401, { error: "Signed Dwelyx headers are required" });
  }

  const parsedTimestamp = Number.parseInt(timestamp, 10);
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (!Number.isFinite(parsedTimestamp) || Math.abs(nowSeconds - parsedTimestamp) > REPLAY_WINDOW_SECONDS) {
    return jsonResponse(401, { error: "Event timestamp is outside the replay window" });
  }

  const body = await request.text();
  if (!body || encoder.encode(body).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { error: "Event body is empty or too large" });
  }

  const expectedSignature = await hmacSignature(body, timestamp, webhookSecret);
  if (!constantTimeEqual(signature, expectedSignature)) {
    return jsonResponse(401, { error: "Invalid event signature" });
  }

  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    return jsonResponse(400, { error: "Event body is not valid JSON" });
  }

  const errors = validatePayload(payload);
  if (errors.length) return jsonResponse(400, { error: "Event contract rejected", details: errors });
  const record = payload as Record<string, unknown>;
  if (record.event_id !== headerEventId) {
    return jsonResponse(400, { error: "Event ID header does not match the body" });
  }

  const supabase = createClient(supabaseUrl, serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });

  const { error: bucketError } = await supabase.storage.getBucket(BUCKET);
  if (bucketError) {
    const { error: createError } = await supabase.storage.createBucket(BUCKET, {
      public: false,
      allowedMimeTypes: ["application/json"],
      fileSizeLimit: MAX_BODY_BYTES,
    });
    if (createError && !createError.message.toLowerCase().includes("already")) {
      return jsonResponse(500, { error: "Could not prepare the private event inbox" });
    }
  }

  const eventPath = `${PREFIX}/${record.event_id}.json`;
  const { error: uploadError } = await supabase.storage.from(BUCKET).upload(eventPath, body, {
    contentType: "application/json",
    cacheControl: "0",
    upsert: false,
  });

  if (uploadError) {
    const message = uploadError.message.toLowerCase();
    if (message.includes("duplicate") || message.includes("already exists") || message.includes("resource already exists")) {
      return jsonResponse(200, { accepted: true, duplicate: true, event_id: record.event_id });
    }
    return jsonResponse(500, { error: "Could not store the event" });
  }

  return jsonResponse(202, { accepted: true, duplicate: false, event_id: record.event_id });
});
