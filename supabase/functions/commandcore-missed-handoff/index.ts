const SERVICE_VERSION = "2026-08-27.1";
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

function parseTime(value: unknown): number | null {
  const parsed = Date.parse(text(value));
  return Number.isFinite(parsed) ? parsed : null;
}

async function postJson(
  url: string,
  serviceKey: string,
  payload: RecordValue,
): Promise<RecordValue> {
  const response = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) return {};
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as RecordValue : {};
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-missed-handoff",
      version: SERVICE_VERSION,
      status: "healthy",
      detection_only: true,
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

  const graceMinutesValue = Number(body.grace_minutes ?? 15);
  const graceMinutes = Number.isFinite(graceMinutesValue) && graceMinutesValue >= 0 ? graceMinutesValue : 15;
  const shiftStartedAt = parseTime(body.shift_started_at);
  if (shiftStartedAt === null) return jsonResponse(422, { ok: false, error: "shift_started_at_required" });

  const nowMs = parseTime(body.now) ?? Date.now();
  const takeoverResponse = await postJson(
    `${supabaseUrl}/functions/v1/commandcore-shift-takeover`,
    serviceKey,
    { action: "list", owner_id: ownerId },
  );
  const latest = takeoverResponse.latest_takeover && typeof takeoverResponse.latest_takeover === "object"
    ? takeoverResponse.latest_takeover as RecordValue
    : null;
  const latestTakeoverAt = latest ? parseTime(latest.taken_over_at) : null;
  const acknowledgedThisShift = latestTakeoverAt !== null && latestTakeoverAt >= shiftStartedAt;
  const elapsedMinutes = Math.max(0, (nowMs - shiftStartedAt) / 60_000);
  const overdue = !acknowledgedThisShift && elapsedMinutes >= graceMinutes;

  let escalationLevel = "normal";
  if (overdue && elapsedMinutes >= graceMinutes + 30) escalationLevel = "critical";
  else if (overdue) escalationLevel = "overdue";
  else if (!acknowledgedThisShift) escalationLevel = "pending";

  return jsonResponse(200, {
    ok: true,
    owner_id: ownerId,
    shift_started_at: new Date(shiftStartedAt).toISOString(),
    evaluated_at: new Date(nowMs).toISOString(),
    grace_minutes: graceMinutes,
    elapsed_minutes: Math.round(elapsedMinutes * 10) / 10,
    acknowledged_this_shift: acknowledgedThisShift,
    latest_takeover: latest,
    handoff_status: acknowledgedThisShift ? "acknowledged" : overdue ? "missed" : "awaiting_acknowledgment",
    escalation_level: escalationLevel,
    requires_attention: overdue,
    recommended_action: acknowledgedThisShift
      ? "No action needed"
      : overdue
        ? "Confirm incoming operator reviewed the shift brief"
        : "Wait for takeover acknowledgment",
    assignment_changed: false,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    external_action_started: false,
  });
});
