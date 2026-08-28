const SERVICE_VERSION = "2026-08-28.1";
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

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-coverage-orchestrator",
      version: SERVICE_VERSION,
      status: "healthy",
      internal_assignment_only: true,
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
  const shiftStartedAt = text(body.shift_started_at);
  const graceMinutes = Number(body.grace_minutes ?? 15);
  const autoApply = body.auto_apply === true;
  if (!ownerId) return jsonResponse(422, { ok: false, error: "owner_id_required" });
  if (!shiftStartedAt) return jsonResponse(422, { ok: false, error: "shift_started_at_required" });

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const detection = await postJson(
    `${supabaseUrl}/functions/v1/commandcore-missed-handoff`,
    serviceKey,
    { owner_id: ownerId, shift_started_at: shiftStartedAt, grace_minutes: Number.isFinite(graceMinutes) ? graceMinutes : 15 },
  );

  if (detection.requires_attention !== true) {
    return jsonResponse(200, {
      ok: true,
      requires_attention: false,
      detection,
      uncovered_work: [],
      backup: null,
      applied_dispatches: [],
      external_action_started: false,
    });
  }

  const uncovered = await postJson(
    `${supabaseUrl}/functions/v1/commandcore-uncovered-work-discovery`,
    serviceKey,
    { owner_id: ownerId },
  );
  const dispatches = Array.isArray(uncovered.dispatches)
    ? uncovered.dispatches.filter((item) => item && typeof item === "object") as RecordValue[]
    : [];

  const handoffStatus = text(detection.handoff_status).toLowerCase();
  const backup = await postJson(
    `${supabaseUrl}/functions/v1/commandcore-coverage-escalation`,
    serviceKey,
    { owner_id: ownerId, handoff_status: handoffStatus, apply: false },
  );

  const appliedDispatches: RecordValue[] = [];
  if (autoApply && backup.backup_available === true) {
    for (const item of dispatches) {
      const dispatchId = text(item.dispatch_id);
      if (!dispatchId) continue;
      try {
        const result = await postJson(
          `${supabaseUrl}/functions/v1/commandcore-coverage-escalation`,
          serviceKey,
          { owner_id: ownerId, dispatch_id: dispatchId, handoff_status: handoffStatus, apply: true },
        );
        appliedDispatches.push({ dispatch_id: dispatchId, ok: result.ok === true, applied: result.applied === true });
      } catch {
        appliedDispatches.push({ dispatch_id: dispatchId, ok: false, applied: false });
      }
    }
  }

  return jsonResponse(200, {
    ok: true,
    requires_attention: true,
    detection,
    uncovered_work: dispatches,
    uncovered_dispatch_count: dispatches.length,
    backup,
    auto_apply_requested: autoApply,
    applied_dispatches: appliedDispatches,
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
