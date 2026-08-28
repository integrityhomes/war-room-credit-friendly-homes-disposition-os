const SERVICE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 64 * 1024;

type QueueItem = Record<string, unknown>;
type OperatorState = Record<string, unknown>;

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

function parseTime(value: unknown): number | null {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function hoursSince(value: unknown, nowMs: number): number | null {
  const time = parseTime(value);
  if (time === null) return null;
  return Math.max(0, (nowMs - time) / 3_600_000);
}

function actionId(item: QueueItem): string {
  return String(item.action_id || `${item.dispatch_id || ""}_${item.channel_key || ""}`).trim();
}

function evaluate(item: QueueItem, state: OperatorState, nowMs: number): Record<string, unknown> {
  const priority = String(item.priority || "medium").toLowerCase();
  const readiness = String(item.readiness || "HOLD").toUpperCase();
  const reviewState = String(state.state || "unacknowledged").toLowerCase();
  const createdHours = hoursSince(item.created_at || item.generated_at, nowMs);
  const reviewedHours = hoursSince(state.updated_at, nowMs);

  const reasons: string[] = [];
  let level = "normal";

  if (readiness === "BLOCKED") {
    level = "critical";
    reasons.push("blocked_item_requires_review");
  }
  if (reviewState === "unacknowledged" && createdHours !== null) {
    const threshold = priority === "high" ? 4 : priority === "medium" ? 12 : 24;
    if (createdHours >= threshold) {
      level = priority === "high" ? "critical" : "overdue";
      reasons.push("unacknowledged_item_aged");
    }
  }
  if (reviewState === "needs_follow_up" && reviewedHours !== null && reviewedHours >= 24) {
    if (level === "normal") level = "overdue";
    reasons.push("follow_up_overdue");
  }
  if (readiness === "MANUAL" && createdHours !== null && createdHours >= 24) {
    if (level === "normal") level = "overdue";
    reasons.push("manual_action_aged");
  }

  return {
    action_id: actionId(item),
    dispatch_id: String(item.dispatch_id || ""),
    property_id: String(item.property_id || ""),
    channel_key: String(item.channel_key || ""),
    readiness,
    priority,
    review_state: reviewState,
    age_hours: createdHours === null ? null : Math.round(createdHours * 10) / 10,
    escalation_level: level,
    escalation_reasons: reasons,
    requires_attention: level !== "normal",
    recommended_action:
      level === "critical" ? "Review now" : level === "overdue" ? "Complete follow-up" : "No escalation",
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-aging-escalation",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      readiness_mutation_enabled: false,
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

  const items = Array.isArray(body.items) ? body.items.filter((item) => item && typeof item === "object") as QueueItem[] : [];
  const states = body.operator_states && typeof body.operator_states === "object" && !Array.isArray(body.operator_states)
    ? body.operator_states as Record<string, OperatorState>
    : {};
  const nowMs = parseTime(body.now) ?? Date.now();
  const escalations = items.map((item) => evaluate(item, states[actionId(item)] || {}, nowMs));
  const attention = escalations.filter((item) => item.requires_attention);

  return jsonResponse(200, {
    ok: true,
    evaluated_at: new Date(nowMs).toISOString(),
    total_items: escalations.length,
    escalated_items: attention.length,
    critical_items: attention.filter((item) => item.escalation_level === "critical").length,
    overdue_items: attention.filter((item) => item.escalation_level === "overdue").length,
    escalations,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    external_action_started: false,
  });
});
