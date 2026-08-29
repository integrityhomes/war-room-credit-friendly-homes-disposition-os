const SERVICE_VERSION = "2026-08-29.1";
const ACTION_BUCKET = "commandcore-action-queue";
const MAX_BODY_BYTES = 64 * 1024;
const MAX_MOVES_PER_RUN = 10;

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
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

function text(value: unknown): string {
  return String(value || "").trim();
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item).toLowerCase()).filter(Boolean) : [];
}

function actionId(item: Row): string {
  return text(item.action_id || `${item.dispatch_id || ""}_${item.channel_key || ""}`);
}

function isLowRisk(item: Row): boolean {
  if (text(item.readiness).toLowerCase() !== "hold") return false;
  if (text(item.priority).toLowerCase() === "high") return false;
  const sensitive = [
    ...stringList(item.reasons),
    ...stringList(item.required_actions),
    text(item.channel_key).toLowerCase(),
  ].join(" ");
  return ![
    "approve",
    "approval",
    "consent",
    "contract",
    "legal",
    "payment",
    "money",
    "wire",
    "bank",
    "offer",
    "signature",
    "sign",
    "send",
    "message",
    "sms",
    "email",
  ].some((term) => sensitive.includes(term));
}

async function callService(
  supabaseUrl: string,
  serviceKey: string,
  service: string,
  payload: Row,
): Promise<Row> {
  const response = await fetch(`${supabaseUrl}/functions/v1/${service}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = parsed && typeof parsed === "object" ? text((parsed as Row).error) : "";
    throw new Error(error || `${service}_unavailable`);
  }
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : {};
}

async function loadAllOpenItems(supabaseUrl: string, serviceKey: string): Promise<Row[]> {
  const listResponse = await fetch(`${supabaseUrl}/storage/v1/object/list/${ACTION_BUCKET}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
    },
    body: JSON.stringify({ prefix: "dispatches", limit: 1000, offset: 0, sortBy: { column: "name", order: "asc" } }),
  });
  if (!listResponse.ok) throw new Error(`action_queue_list_failed_${listResponse.status}`);
  const files = await listResponse.json() as Row[];
  const items: Row[] = [];

  for (const file of files) {
    const name = text(file.name);
    if (!name.endsWith(".json")) continue;
    const path = `dispatches/${encodeURIComponent(name)}`;
    const response = await fetch(`${supabaseUrl}/storage/v1/object/authenticated/${ACTION_BUCKET}/${path}`, {
      headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
    });
    if (!response.ok) continue;
    const queue = await response.json() as Row;
    const dispatchId = text(queue.dispatch_id || name.replace(/\.json$/, ""));
    const queueItems = Array.isArray(queue.items) ? queue.items.filter((item) => item && typeof item === "object") as Row[] : [];
    for (const item of queueItems) {
      const readiness = text(item.readiness).toLowerCase();
      if (!["hold", "manual", "blocked"].includes(readiness)) continue;
      items.push({ ...item, dispatch_id: text(item.dispatch_id) || dispatchId });
    }
  }
  return items;
}

function noWorkResponse(apply: boolean): Row {
  return {
    ok: true,
    generated_at: new Date().toISOString(),
    apply_requested: apply,
    open_items: 0,
    advisor_recommendations: 0,
    eligible_low_risk_high_confidence: 0,
    eligible: [],
    applied_count: 0,
    applied: [],
    skipped: [],
    no_work: true,
    assignment_only: true,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    external_action_started: false,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-auto-rebalance",
      version: SERVICE_VERSION,
      status: "healthy",
      low_risk_assignment_only: true,
      high_confidence_only: true,
      max_moves_per_run: MAX_MOVES_PER_RUN,
      external_execution_enabled: false,
      readiness_mutation_enabled: false,
      approval_mutation_enabled: false,
      consent_mutation_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Row = {};
  if (raw.trim()) {
    try {
      body = JSON.parse(raw) as Row;
    } catch {
      return jsonResponse(400, { ok: false, error: "invalid_json" });
    }
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const apply = body.apply === true;
  try {
    const openItems = await loadAllOpenItems(supabaseUrl, serviceKey);
    if (!openItems.length) return jsonResponse(200, noWorkResponse(apply));

    const advisor = await callService(supabaseUrl, serviceKey, "commandcore-workload-balance-advisor", { items: openItems });
    const recommendations = Array.isArray(advisor.recommendations)
      ? advisor.recommendations.filter((item) => item && typeof item === "object") as Row[]
      : [];
    const itemByActionId = new Map(openItems.map((item) => [actionId(item), item]));

    const eligible = recommendations.filter((recommendation) => {
      if (text(recommendation.confidence).toLowerCase() !== "high") return false;
      const item = itemByActionId.get(text(recommendation.action_id));
      return Boolean(item && isLowRisk(item));
    }).slice(0, MAX_MOVES_PER_RUN);

    const applied: Row[] = [];
    const skipped: Row[] = [];
    if (apply) {
      for (const recommendation of eligible) {
        try {
          const result = await callService(supabaseUrl, serviceKey, "commandcore-safe-rebalance-apply", {
            apply: true,
            dispatch_id: recommendation.dispatch_id,
            action_id: recommendation.action_id,
            from_owner_id: recommendation.from_owner_id,
            to_owner_id: recommendation.to_owner_id,
            reason: `automatic_high_confidence_rebalance: ${text(recommendation.reason)}`,
          });
          applied.push({
            action_id: recommendation.action_id,
            dispatch_id: recommendation.dispatch_id,
            from_owner_id: recommendation.from_owner_id,
            to_owner_id: recommendation.to_owner_id,
            applied: result.applied === true,
          });
        } catch (error) {
          skipped.push({
            action_id: recommendation.action_id,
            dispatch_id: recommendation.dispatch_id,
            reason: error instanceof Error ? error.message : "apply_failed",
          });
        }
      }
    }

    return jsonResponse(200, {
      ok: true,
      generated_at: new Date().toISOString(),
      apply_requested: apply,
      open_items: openItems.length,
      advisor_recommendations: recommendations.length,
      eligible_low_risk_high_confidence: eligible.length,
      eligible,
      applied_count: applied.length,
      applied,
      skipped,
      no_work: false,
      assignment_only: true,
      readiness_changed: false,
      approval_changed: false,
      consent_changed: false,
      external_action_started: false,
    });
  } catch (error) {
    return jsonResponse(503, {
      ok: false,
      error: "rebalance_dependency_unavailable",
      detail: error instanceof Error ? error.message : "unknown_dependency_error",
      apply_requested: apply,
      applied_count: 0,
      assignment_only: true,
      readiness_changed: false,
      approval_changed: false,
      consent_changed: false,
      external_action_started: false,
    });
  }
});
