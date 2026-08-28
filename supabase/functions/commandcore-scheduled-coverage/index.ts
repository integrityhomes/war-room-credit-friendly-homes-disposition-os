const SERVICE_VERSION = "2026-08-28.2";
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

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item).toLowerCase()).filter(Boolean) : [];
}

function timeMinutes(value: unknown, fallback: number): number {
  const raw = text(value);
  const match = raw.match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) return fallback;
  return Number(match[1]) * 60 + Number(match[2]);
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
  return {
    day: get("weekday").slice(0, 3).toLowerCase(),
    minutes: Number(get("hour")) * 60 + Number(get("minute")),
  };
}

function shiftElapsedMinutes(member: RecordValue, now: Date): number | null {
  const timezone = text(member.timezone) || "America/New_York";
  let local: { day: string; minutes: number };
  try {
    local = localParts(now, timezone);
  } catch {
    local = localParts(now, "America/New_York");
  }

  const days = stringList(member.shift_days);
  const allowedDays = days.length ? days : ["mon", "tue", "wed", "thu", "fri"];
  const start = timeMinutes(member.shift_start, 9 * 60);
  const end = timeMinutes(member.shift_end, 17 * 60);
  if (start === end) return null;

  if (start < end) {
    if (!allowedDays.includes(local.day) || local.minutes < start || local.minutes >= end) return null;
    return local.minutes - start;
  }

  if (local.minutes >= start) {
    if (!allowedDays.includes(local.day)) return null;
    return local.minutes - start;
  }

  if (local.minutes < end) {
    return 1440 - start + local.minutes;
  }
  return null;
}

async function postJson(url: string, serviceKey: string, payload: RecordValue): Promise<RecordValue> {
  const response = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`downstream_${response.status}`);
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as RecordValue : {};
}

function stableExceptionId(ownerId: string, shiftStartedAt: string, kind: string, dispatchId = ""): string {
  const shiftKey = shiftStartedAt.replace(/[^0-9a-z]+/gi, "-").replace(/^-+|-+$/g, "");
  const dispatchKey = dispatchId ? `-${dispatchId.replace(/[^0-9a-z._-]+/gi, "-")}` : "";
  return `${ownerId}-${shiftKey}-${kind}${dispatchKey}`.toLowerCase();
}

async function recordException(
  supabaseUrl: string,
  serviceKey: string,
  record: RecordValue,
): Promise<boolean> {
  try {
    const result = await postJson(
      `${supabaseUrl}/functions/v1/commandcore-coverage-exception-ledger`,
      serviceKey,
      { exception: record },
    );
    return result.ok === true || Number(result.written || 0) > 0;
  } catch {
    return false;
  }
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-scheduled-coverage",
      version: SERVICE_VERSION,
      status: "healthy",
      schedule_driven: true,
      assignment_only: true,
      exception_ledger_enabled: true,
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

  const parsedNow = Date.parse(text(body.now));
  const now = new Date(Number.isFinite(parsedNow) ? parsedNow : Date.now());
  const graceValue = Number(body.grace_minutes ?? 15);
  const graceMinutes = Number.isFinite(graceValue) && graceValue >= 0 ? graceValue : 15;
  const autoApply = body.auto_apply !== false;

  const registry = await postJson(
    `${supabaseUrl}/functions/v1/commandcore-team-registry`,
    serviceKey,
    { action: "list" },
  );
  const members = Array.isArray(registry.members)
    ? registry.members.filter((item) => item && typeof item === "object") as RecordValue[]
    : [];

  const evaluations: RecordValue[] = [];
  let exceptionsRecorded = 0;
  let exceptionWriteFailures = 0;

  for (const member of members) {
    const ownerId = text(member.id || member.user_id || member.email || member.name);
    const ownerName = text(member.name || ownerId);
    if (!ownerId || member.active === false) continue;
    const elapsed = shiftElapsedMinutes(member, now);
    if (elapsed === null || elapsed < graceMinutes) continue;

    const shiftStartedAt = new Date(now.getTime() - elapsed * 60_000).toISOString();
    try {
      const result = await postJson(
        `${supabaseUrl}/functions/v1/commandcore-coverage-orchestrator`,
        serviceKey,
        {
          owner_id: ownerId,
          shift_started_at: shiftStartedAt,
          grace_minutes: graceMinutes,
          auto_apply: autoApply,
        },
      );

      const applied = Array.isArray(result.applied_dispatches)
        ? result.applied_dispatches.filter((item) => item && typeof item === "object") as RecordValue[]
        : [];
      const failedDispatches = applied.filter((item) => item.ok !== true || item.applied !== true);
      const backup = result.backup && typeof result.backup === "object" && !Array.isArray(result.backup)
        ? result.backup as RecordValue
        : {};
      const noBackup = result.requires_attention === true && backup.backup_available !== true;

      if (noBackup) {
        const recorded = await recordException(supabaseUrl, serviceKey, {
          exception_id: stableExceptionId(ownerId, shiftStartedAt, "no-eligible-backup"),
          owner_id: ownerId,
          owner_name: ownerName,
          severity: "critical",
          source: "commandcore-scheduled-coverage",
          status: "open",
          exception_type: "no_eligible_backup",
          shift_started_at: shiftStartedAt,
          created_at: shiftStartedAt,
          uncovered_dispatch_count: Number(result.uncovered_dispatch_count || 0),
          handoff_status: text((result.detection as RecordValue | undefined)?.handoff_status),
          recommended_action: text(backup.recommended_action) || "Manager coverage review required.",
        });
        if (recorded) exceptionsRecorded += 1;
        else exceptionWriteFailures += 1;
      }

      for (const failed of failedDispatches) {
        const dispatchId = text(failed.dispatch_id);
        const recorded = await recordException(supabaseUrl, serviceKey, {
          exception_id: stableExceptionId(ownerId, shiftStartedAt, "reassignment-failed", dispatchId),
          owner_id: ownerId,
          owner_name: ownerName,
          severity: "critical",
          source: "commandcore-scheduled-coverage",
          status: "open",
          exception_type: "reassignment_failed",
          dispatch_id: dispatchId,
          shift_started_at: shiftStartedAt,
          created_at: shiftStartedAt,
          context: failed,
          recommended_action: "Confirm coverage for this dispatch and review why automatic reassignment failed.",
        });
        if (recorded) exceptionsRecorded += 1;
        else exceptionWriteFailures += 1;
      }

      evaluations.push({
        owner_id: ownerId,
        owner_name: ownerName,
        shift_started_at: shiftStartedAt,
        elapsed_minutes: elapsed,
        requires_attention: result.requires_attention === true,
        uncovered_dispatch_count: Number(result.uncovered_dispatch_count || 0),
        applied_dispatches: result.applied_dispatches || [],
        exception_count: (noBackup ? 1 : 0) + failedDispatches.length,
        ok: result.ok === true,
      });
    } catch (error) {
      const recorded = await recordException(supabaseUrl, serviceKey, {
        exception_id: stableExceptionId(ownerId, shiftStartedAt, "coverage-processing-failed"),
        owner_id: ownerId,
        owner_name: ownerName,
        severity: "critical",
        source: "commandcore-scheduled-coverage",
        status: "open",
        exception_type: "coverage_processing_failed",
        shift_started_at: shiftStartedAt,
        created_at: shiftStartedAt,
        error: String(error),
        recommended_action: "Review the scheduled coverage service and confirm this shift is safely covered.",
      });
      if (recorded) exceptionsRecorded += 1;
      else exceptionWriteFailures += 1;
      evaluations.push({
        owner_id: ownerId,
        owner_name: ownerName,
        shift_started_at: shiftStartedAt,
        elapsed_minutes: elapsed,
        exception_count: 1,
        ok: false,
      });
    }
  }

  return jsonResponse(200, {
    ok: true,
    evaluated_at: now.toISOString(),
    grace_minutes: graceMinutes,
    auto_apply: autoApply,
    active_shift_members_evaluated: evaluations.length,
    attention_required_count: evaluations.filter((item) => item.requires_attention === true).length,
    exceptions_recorded: exceptionsRecorded,
    exception_write_failures: exceptionWriteFailures,
    evaluations,
    assignment_only: true,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    legal_terms_changed: false,
    payment_started: false,
    external_action_started: false,
  });
});
