const SERVICE_VERSION = "2026-08-28.1";
const BUCKET = "commandcore-team-registry";
const MAX_BODY_BYTES = 64 * 1024;

type TeamMember = Record<string, unknown>;

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function isAuthenticated(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const auth = req.headers.get("authorization") || "";
  const supplied = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function memberId(member: TeamMember): string {
  return String(member.id || member.user_id || member.email || member.name || "").trim();
}

function cleanList(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.map((item) => String(item).trim().toLowerCase()).filter(Boolean))]
    : [];
}

function normalizeAvailability(value: unknown): string {
  const normalized = String(value || "available").trim().toLowerCase();
  return ["available", "away", "unavailable"].includes(normalized) ? normalized : "available";
}

function normalizeMember(member: TeamMember): TeamMember {
  const id = memberId(member);
  const maxLoadRaw = Number(member.max_load ?? 20);
  const currentLoadRaw = Number(member.current_load ?? 0);
  const unavailableUntil = String(member.unavailable_until || "").trim();
  return {
    id,
    name: String(member.name || id).trim(),
    email: String(member.email || "").trim().toLowerCase(),
    active: member.active !== false,
    availability: normalizeAvailability(member.availability),
    unavailable_until: unavailableUntil || null,
    roles: cleanList(member.roles),
    skills: cleanList(member.skills),
    channels: cleanList(member.channels),
    max_load: Number.isFinite(maxLoadRaw) && maxLoadRaw > 0 ? maxLoadRaw : 20,
    current_load: Number.isFinite(currentLoadRaw) && currentLoadRaw >= 0 ? currentLoadRaw : 0,
    updated_at: new Date().toISOString(),
  };
}

async function ensureBucket(supabaseUrl: string, serviceKey: string): Promise<void> {
  const list = await fetch(`${supabaseUrl}/storage/v1/bucket`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!list.ok) throw new Error("storage_bucket_list_failed");
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
  if (!created.ok && created.status !== 409) throw new Error("storage_bucket_create_failed");
}

async function writeMember(supabaseUrl: string, serviceKey: string, member: TeamMember): Promise<void> {
  const id = encodeURIComponent(memberId(member));
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${BUCKET}/members/${id}.json`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "x-upsert": "true",
      "content-type": "application/json",
    },
    body: JSON.stringify(member),
  });
  if (!response.ok) throw new Error("team_member_write_failed");
}

async function listMembers(supabaseUrl: string, serviceKey: string): Promise<TeamMember[]> {
  const response = await fetch(`${supabaseUrl}/storage/v1/object/list/${BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix: "members", limit: 1000, offset: 0, sortBy: { column: "name", order: "asc" } }),
  });
  if (!response.ok) throw new Error("team_member_list_failed");
  const rows = await response.json() as Array<Record<string, unknown>>;
  const members: TeamMember[] = [];
  for (const row of rows) {
    const name = String(row.name || "");
    if (!name.endsWith(".json")) continue;
    const object = await fetch(`${supabaseUrl}/storage/v1/object/authenticated/${BUCKET}/members/${encodeURIComponent(name)}`, {
      headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
    });
    if (!object.ok) continue;
    const parsed = await object.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) members.push(parsed as TeamMember);
  }
  return members;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-team-registry",
      version: SERVICE_VERSION,
      status: "healthy",
      public_registry: false,
      external_execution_enabled: false,
      availability_tracking_enabled: true,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });
  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  await ensureBucket(supabaseUrl, serviceKey);
  const action = String(body.action || "list").trim().toLowerCase();

  if (action === "list") {
    const members = await listMembers(supabaseUrl, serviceKey);
    return jsonResponse(200, { ok: true, members, total_members: members.length });
  }

  if (action === "upsert") {
    if (!body.member || typeof body.member !== "object" || Array.isArray(body.member)) {
      return jsonResponse(422, { ok: false, error: "member_required" });
    }
    const normalized = normalizeMember(body.member as TeamMember);
    if (!memberId(normalized)) return jsonResponse(422, { ok: false, error: "member_id_required" });
    await writeMember(supabaseUrl, serviceKey, normalized);
    return jsonResponse(200, {
      ok: true,
      member: normalized,
      readiness_changed: false,
      approval_changed: false,
      external_action_started: false,
    });
  }

  return jsonResponse(422, { ok: false, error: "unsupported_action" });
});
