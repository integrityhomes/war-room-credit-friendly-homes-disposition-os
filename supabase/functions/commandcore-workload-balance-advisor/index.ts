const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 256 * 1024;

type Row = Record<string, unknown>;

type Recommendation = {
  action_id: string;
  dispatch_id: string;
  property_id: string;
  channel_key: string;
  from_owner_id: string;
  from_owner_name: string;
  to_owner_id: string;
  to_owner_name: string;
  from_load_percent: number;
  to_load_percent_before: number;
  to_load_percent_after: number;
  reason: string;
  confidence: "high" | "medium";
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

function text(value: unknown): string {
  return String(value || "").trim();
}

function memberId(member: Row): string {
  return text(member.id || member.user_id || member.email || member.name);
}

function maxLoad(member: Row): number {
  const value = Number(member.max_load ?? 20);
  return Number.isFinite(value) && value > 0 ? value : 20;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item).toLowerCase()).filter(Boolean) : [];
}

function actionId(item: Row): string {
  return text(item.action_id || `${item.dispatch_id || ""}_${item.channel_key || ""}`);
}

function isOpen(item: Row): boolean {
  return ["hold", "manual", "blocked"].includes(text(item.readiness).toLowerCase());
}

function isCoverageAvailable(row: Row | undefined): boolean {
  return row?.available === true;
}

async function callService(
  supabaseUrl: string,
  serviceKey: string,
  service: string,
  payload: Record<string, unknown>,
): Promise<Row> {
  const response = await fetch(`${supabaseUrl}/functions/v1/${service}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${service}_unavailable`);
  const parsed = await response.json();
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Row : {};
}

function scoreReceiver(item: Row, member: Row, newLoad: number): { score: number; reason: string; confidence: "high" | "medium" } {
  const channel = text(item.channel_key).toLowerCase();
  const channels = stringList(member.channels);
  const skills = stringList(member.skills);
  const roles = stringList(member.roles);
  const reasons = stringList(item.reasons);
  const required = stringList(item.required_actions);
  let score = 0;
  const why: string[] = [];

  if (channel && channels.includes(channel)) {
    score += 35;
    why.push("channel match");
  }
  if (text(item.readiness).toLowerCase() === "manual" && roles.includes("operator")) {
    score += 15;
    why.push("operator match");
  }
  if (reasons.some((value) => value.includes("consent")) && skills.includes("compliance")) {
    score += 20;
    why.push("compliance match");
  }
  if (reasons.some((value) => value.includes("connection")) && skills.includes("integrations")) {
    score += 20;
    why.push("integration match");
  }
  if (required.some((value) => value.includes("approve")) && roles.includes("approver")) {
    score += 15;
    why.push("approver match");
  }

  const capacity = Math.max(0, 1 - newLoad / maxLoad(member));
  score += capacity * 30;
  why.push("lower workload");
  return {
    score,
    reason: why.join(", "),
    confidence: score >= 55 ? "high" : "medium",
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-workload-balance-advisor",
      version: SERVICE_VERSION,
      status: "healthy",
      recommendation_only: true,
      automatic_assignment_enabled: false,
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
    body = JSON.parse(raw) as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const items = Array.isArray(body.items)
    ? body.items.filter((item) => item && typeof item === "object") as Row[]
    : [];
  if (!items.length) return jsonResponse(422, { ok: false, error: "items_required" });

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const [registry, coverageResult] = await Promise.all([
    callService(supabaseUrl, serviceKey, "commandcore-team-registry", { action: "list" }),
    callService(supabaseUrl, serviceKey, "commandcore-team-coverage", {}),
  ]);
  const members = Array.isArray(registry.members) ? registry.members.filter((item) => item && typeof item === "object") as Row[] : [];
  const coverage = Array.isArray(coverageResult.coverage)
    ? coverageResult.coverage.filter((item) => item && typeof item === "object") as Row[]
    : [];
  const coverageById = new Map(coverage.map((item) => [text(item.id).toLowerCase(), item]));
  const membersById = new Map(members.map((item) => [memberId(item).toLowerCase(), item]));

  const openItems = items.filter(isOpen);
  const loads = new Map<string, number>();
  for (const item of openItems) {
    const id = text(item.owner_id).toLowerCase();
    if (id) loads.set(id, (loads.get(id) || 0) + 1);
  }

  const overloadedIds = new Set(
    members
      .filter((member) => {
        const id = memberId(member).toLowerCase();
        const load = loads.get(id) || 0;
        return member.active !== false && load / maxLoad(member) >= 0.8;
      })
      .map((member) => memberId(member).toLowerCase()),
  );

  const mutableLoads = new Map(loads);
  const recommendations: Recommendation[] = [];

  const candidateItems = openItems
    .filter((item) => overloadedIds.has(text(item.owner_id).toLowerCase()))
    .sort((left, right) => {
      const priority = (value: Row) => text(value.priority).toLowerCase() === "high" ? 0 : 1;
      return priority(left) - priority(right);
    });

  for (const item of candidateItems) {
    const fromId = text(item.owner_id).toLowerCase();
    const fromMember = membersById.get(fromId);
    if (!fromMember) continue;
    const fromLoad = mutableLoads.get(fromId) || 0;
    const fromRatio = fromLoad / maxLoad(fromMember);
    if (fromRatio < 0.8) continue;

    const receivers = members
      .filter((member) => {
        const id = memberId(member).toLowerCase();
        if (!id || id === fromId || member.active === false) return false;
        if (!isCoverageAvailable(coverageById.get(id))) return false;
        const load = mutableLoads.get(id) || 0;
        return load / maxLoad(member) < 0.6 && load + 1 <= maxLoad(member);
      })
      .map((member) => {
        const id = memberId(member).toLowerCase();
        const load = mutableLoads.get(id) || 0;
        return { member, id, load, ...scoreReceiver(item, member, load + 1) };
      })
      .sort((left, right) => right.score - left.score || left.load - right.load);

    const winner = receivers[0];
    if (!winner) continue;

    const beforeRatio = winner.load / maxLoad(winner.member);
    const afterLoad = winner.load + 1;
    const afterRatio = afterLoad / maxLoad(winner.member);
    mutableLoads.set(fromId, Math.max(0, fromLoad - 1));
    mutableLoads.set(winner.id, afterLoad);

    recommendations.push({
      action_id: actionId(item),
      dispatch_id: text(item.dispatch_id),
      property_id: text(item.property_id),
      channel_key: text(item.channel_key),
      from_owner_id: memberId(fromMember),
      from_owner_name: text(fromMember.name || memberId(fromMember)),
      to_owner_id: memberId(winner.member),
      to_owner_name: text(winner.member.name || memberId(winner.member)),
      from_load_percent: Math.round(fromRatio * 100),
      to_load_percent_before: Math.round(beforeRatio * 100),
      to_load_percent_after: Math.round(afterRatio * 100),
      reason: winner.reason,
      confidence: winner.confidence,
    });
  }

  return jsonResponse(200, {
    ok: true,
    generated_at: new Date().toISOString(),
    open_items: openItems.length,
    overloaded_team_members: overloadedIds.size,
    recommendations,
    recommendation_count: recommendations.length,
    recommendation_only: true,
    readiness_changed: false,
    approval_changed: false,
    external_action_started: false,
  });
});
