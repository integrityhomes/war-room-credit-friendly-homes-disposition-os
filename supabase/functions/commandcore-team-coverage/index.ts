const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 64 * 1024;

type TeamMember = Record<string, unknown>;

type CoverageMember = {
  id: string;
  name: string;
  on_shift: boolean;
  available: boolean;
  after_hours_eligible: boolean;
  coverage_state: string;
  backup_owner_ids: string[];
};

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

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item).trim().toLowerCase()).filter(Boolean) : [];
}

function localParts(now: Date, timezone: string): { day: string; minutes: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (type: string) => parts.find((part) => part.type === type)?.value || "";
  const day = get("weekday").slice(0, 3).toLowerCase();
  const hour = Number(get("hour"));
  const minute = Number(get("minute"));
  return { day, minutes: hour * 60 + minute };
}

function timeMinutes(value: unknown, fallback: number): number {
  const raw = String(value || "").trim();
  const match = raw.match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) return fallback;
  return Number(match[1]) * 60 + Number(match[2]);
}

function onShift(member: TeamMember, now: Date): boolean {
  const timezone = String(member.timezone || "America/New_York").trim();
  let local;
  try {
    local = localParts(now, timezone);
  } catch {
    local = localParts(now, "America/New_York");
  }
  const days = stringList(member.shift_days);
  const allowedDays = days.length ? days : ["mon", "tue", "wed", "thu", "fri"];
  if (!allowedDays.includes(local.day)) return false;
  const start = timeMinutes(member.shift_start, 9 * 60);
  const end = timeMinutes(member.shift_end, 17 * 60);
  if (start === end) return true;
  if (start < end) return local.minutes >= start && local.minutes < end;
  return local.minutes >= start || local.minutes < end;
}

function manuallyAvailable(member: TeamMember, nowMs: number): boolean {
  if (member.active === false || !memberId(member)) return false;
  const status = String(member.availability || "available").trim().toLowerCase();
  if (status === "available") return true;
  const until = Date.parse(String(member.unavailable_until || ""));
  return Number.isFinite(until) && until <= nowMs;
}

async function loadRegistryMembers(): Promise<TeamMember[]> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return [];
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-team-registry`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({ action: "list" }),
  });
  if (!response.ok) return [];
  const parsed = await response.json() as Record<string, unknown>;
  return Array.isArray(parsed.members)
    ? parsed.members.filter((item) => item && typeof item === "object") as TeamMember[]
    : [];
}

function evaluate(member: TeamMember, now: Date): CoverageMember {
  const id = memberId(member);
  const shift = onShift(member, now);
  const manual = manuallyAvailable(member, now.getTime());
  const afterHours = member.after_hours_eligible === true;
  const available = manual && (shift || afterHours);
  let state = "off_shift";
  if (!manual) state = "unavailable";
  else if (shift) state = "on_shift";
  else if (afterHours) state = "after_hours_backup";
  return {
    id,
    name: String(member.name || id).trim(),
    on_shift: shift,
    available,
    after_hours_eligible: afterHours,
    coverage_state: state,
    backup_owner_ids: stringList(member.backup_owner_ids),
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-team-coverage",
      version: SERVICE_VERSION,
      status: "healthy",
      assignment_only: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });
  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw || "{}") as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const supplied = Array.isArray(body.team_members)
    ? body.team_members.filter((item) => item && typeof item === "object") as TeamMember[]
    : [];
  const members = supplied.length ? supplied : await loadRegistryMembers();
  const parsedNow = Date.parse(String(body.now || ""));
  const now = new Date(Number.isFinite(parsedNow) ? parsedNow : Date.now());
  const coverage = members.filter((member) => memberId(member)).map((member) => evaluate(member, now));
  const onShift = coverage.filter((member) => member.coverage_state === "on_shift");
  const backups = coverage.filter((member) => member.coverage_state === "after_hours_backup");
  const available = coverage.filter((member) => member.available);

  return jsonResponse(200, {
    ok: true,
    evaluated_at: now.toISOString(),
    total_team_members: coverage.length,
    on_shift_count: onShift.length,
    after_hours_backup_count: backups.length,
    available_count: available.length,
    coverage_gap: available.length === 0,
    coverage,
    recommended_primary_owner_ids: onShift.map((member) => member.id),
    recommended_backup_owner_ids: backups.map((member) => member.id),
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    external_action_started: false,
  });
});
