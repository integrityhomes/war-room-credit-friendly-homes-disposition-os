const SERVICE_VERSION = "2026-08-27.1";
const MAX_BODY_BYTES = 64 * 1024;

type QueueItem = Record<string, unknown>;
type TeamMember = Record<string, unknown>;

type Assignment = {
  action_id: string;
  owner_id: string;
  owner_name: string;
  routing_reason: string;
  capacity_score: number;
  workload_after_assignment: number;
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

function actionId(item: QueueItem): string {
  return String(item.action_id || `${item.dispatch_id || ""}_${item.channel_key || ""}`).trim();
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item).trim().toLowerCase()).filter(Boolean) : [];
}

function currentLoad(member: TeamMember): number {
  const value = Number(member.current_load ?? 0);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function maxLoad(member: TeamMember): number {
  const value = Number(member.max_load ?? 20);
  return Number.isFinite(value) && value > 0 ? value : 20;
}

function memberId(member: TeamMember): string {
  return String(member.id || member.user_id || member.email || member.name || "").trim();
}

function isActive(member: TeamMember): boolean {
  return member.active !== false && memberId(member).length > 0;
}

function scoreMember(item: QueueItem, member: TeamMember, dealOwner: string): { score: number; reason: string } {
  const id = memberId(member).toLowerCase();
  const name = String(member.name || "").trim().toLowerCase();
  const skills = stringList(member.skills);
  const channels = stringList(member.channels);
  const roles = stringList(member.roles);
  const channel = String(item.channel_key || "").trim().toLowerCase();
  const readiness = String(item.readiness || "").trim().toLowerCase();
  const reasons = stringList(item.reasons);
  const requiredActions = stringList(item.required_actions);
  const ownerHint = String(item.owner_id || item.assignee_id || item.deal_owner || dealOwner || "").trim().toLowerCase();

  let score = 0;
  const why: string[] = [];

  if (ownerHint && (id === ownerHint || name === ownerHint)) {
    score += 100;
    why.push("deal_owner_match");
  }
  if (channel && channels.includes(channel)) {
    score += 25;
    why.push("channel_skill_match");
  }
  if (readiness === "manual" && roles.includes("operator")) {
    score += 10;
    why.push("manual_operator_match");
  }
  if (reasons.some((reason) => reason.includes("consent")) && skills.includes("compliance")) {
    score += 20;
    why.push("compliance_match");
  }
  if (reasons.some((reason) => reason.includes("connection")) && skills.includes("integrations")) {
    score += 20;
    why.push("integration_match");
  }
  if (requiredActions.some((action) => action.includes("approve")) && roles.includes("approver")) {
    score += 15;
    why.push("approver_match");
  }

  const load = currentLoad(member);
  const capacity = Math.max(0, 1 - load / maxLoad(member));
  score += capacity * 20;
  why.push("capacity_weighted");

  return { score, reason: why.join(",") || "lowest_available_load" };
}

function chooseOwner(item: QueueItem, members: TeamMember[], mutableLoads: Map<string, number>, dealOwner: string): Assignment | null {
  const active = members.filter(isActive).filter((member) => {
    const id = memberId(member);
    const assigned = mutableLoads.get(id) ?? currentLoad(member);
    return assigned < maxLoad(member);
  });
  if (!active.length) return null;

  const ranked = active
    .map((member) => {
      const id = memberId(member);
      const assignedLoad = mutableLoads.get(id) ?? currentLoad(member);
      const adjusted = { ...member, current_load: assignedLoad };
      const scored = scoreMember(item, adjusted, dealOwner);
      return { member, id, assignedLoad, ...scored };
    })
    .sort((left, right) => right.score - left.score || left.assignedLoad - right.assignedLoad || left.id.localeCompare(right.id));

  const winner = ranked[0];
  const newLoad = winner.assignedLoad + 1;
  mutableLoads.set(winner.id, newLoad);
  return {
    action_id: actionId(item),
    owner_id: winner.id,
    owner_name: String(winner.member.name || winner.id),
    routing_reason: winner.reason,
    capacity_score: Math.round(winner.score * 10) / 10,
    workload_after_assignment: newLoad,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-owner-routing",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      assignment_only: true,
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
  const members = Array.isArray(body.team_members) ? body.team_members.filter((item) => item && typeof item === "object") as TeamMember[] : [];
  const dealOwners = body.deal_owners && typeof body.deal_owners === "object" && !Array.isArray(body.deal_owners)
    ? body.deal_owners as Record<string, string>
    : {};

  if (!members.some(isActive)) return jsonResponse(422, { ok: false, error: "no_active_team_members" });

  const mutableLoads = new Map<string, number>();
  const assignments: Assignment[] = [];
  const unassigned: string[] = [];

  for (const item of items) {
    const propertyId = String(item.property_id || "").trim();
    const dealOwner = String(dealOwners[propertyId] || "").trim();
    const assignment = chooseOwner(item, members, mutableLoads, dealOwner);
    if (assignment) assignments.push(assignment);
    else unassigned.push(actionId(item));
  }

  return jsonResponse(200, {
    ok: true,
    total_items: items.length,
    assigned_items: assignments.length,
    unassigned_items: unassigned.length,
    assignments,
    unassigned_action_ids: unassigned,
    routing_mutated_readiness: false,
    approval_changed: false,
    consent_changed: false,
    external_action_started: false,
  });
});
