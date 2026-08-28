const SERVICE_VERSION = "2026-08-28.1";
const MAX_BODY_BYTES = 128 * 1024;
const ACTION_BUCKET = "commandcore-action-queue";

type QueueItem = Record<string, unknown>;
type TeamMember = Record<string, unknown>;

type Reassignment = {
  action_id: string;
  previous_owner_id: string | null;
  previous_owner_name: string | null;
  owner_id: string;
  owner_name: string;
  routing_reason: string;
  reassignment_reason: string;
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

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item).trim().toLowerCase()).filter(Boolean) : [];
}

function actionId(item: QueueItem): string {
  return String(item.action_id || `${item.dispatch_id || ""}_${item.channel_key || ""}`).trim();
}

function memberId(member: TeamMember): string {
  return String(member.id || member.user_id || member.email || member.name || "").trim();
}

function currentLoad(member: TeamMember): number {
  const value = Number(member.current_load ?? 0);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}

function maxLoad(member: TeamMember): number {
  const value = Number(member.max_load ?? 20);
  return Number.isFinite(value) && value > 0 ? value : 20;
}

function availability(member: TeamMember): string {
  return String(member.availability || "available").trim().toLowerCase();
}

function unavailableUntil(member: TeamMember): number | null {
  const parsed = Date.parse(String(member.unavailable_until || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function isAvailable(member: TeamMember, nowMs: number): boolean {
  if (member.active === false || !memberId(member)) return false;
  const status = availability(member);
  if (status === "available") return true;
  const until = unavailableUntil(member);
  if (until !== null && until <= nowMs) return true;
  return false;
}

function ownerNeedsReassignment(item: QueueItem, membersById: Map<string, TeamMember>, nowMs: number): string | null {
  const ownerId = String(item.owner_id || "").trim();
  if (!ownerId) return "unassigned";
  const member = membersById.get(ownerId.toLowerCase());
  if (!member) return "owner_missing_from_registry";
  if (member.active === false) return "owner_inactive";
  if (!isAvailable(member, nowMs)) return "owner_unavailable";
  if (currentLoad(member) >= maxLoad(member)) return "owner_at_capacity";
  return null;
}

function scoreMember(item: QueueItem, member: TeamMember, assignedLoad: number): { score: number; reason: string } {
  const skills = stringList(member.skills);
  const channels = stringList(member.channels);
  const roles = stringList(member.roles);
  const channel = String(item.channel_key || "").trim().toLowerCase();
  const readiness = String(item.readiness || "").trim().toLowerCase();
  const reasons = stringList(item.reasons);
  const requiredActions = stringList(item.required_actions);

  let score = 0;
  const why: string[] = [];

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

  const capacity = Math.max(0, 1 - assignedLoad / maxLoad(member));
  score += capacity * 30;
  why.push("capacity_weighted");
  return { score, reason: why.join(",") || "lowest_available_load" };
}

function chooseReplacement(
  item: QueueItem,
  members: TeamMember[],
  mutableLoads: Map<string, number>,
  currentOwnerId: string,
  nowMs: number,
): { member: TeamMember; id: string; newLoad: number; reason: string } | null {
  const candidates = members.filter((member) => {
    const id = memberId(member);
    if (!isAvailable(member, nowMs) || id.toLowerCase() === currentOwnerId.toLowerCase()) return false;
    const load = mutableLoads.get(id) ?? currentLoad(member);
    return load < maxLoad(member);
  });
  if (!candidates.length) return null;

  const ranked = candidates.map((member) => {
    const id = memberId(member);
    const load = mutableLoads.get(id) ?? currentLoad(member);
    const scored = scoreMember(item, member, load);
    return { member, id, load, ...scored };
  }).sort((left, right) => right.score - left.score || left.load - right.load || left.id.localeCompare(right.id));

  const winner = ranked[0];
  const newLoad = winner.load + 1;
  mutableLoads.set(winner.id, newLoad);
  return { member: winner.member, id: winner.id, newLoad, reason: winner.reason };
}

async function loadRegistryMembers(supabaseUrl: string, serviceKey: string): Promise<TeamMember[]> {
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-team-registry`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({ action: "list" }),
  });
  if (!response.ok) throw new Error("team_registry_unavailable");
  const parsed = await response.json() as Record<string, unknown>;
  return Array.isArray(parsed.members)
    ? parsed.members.filter((item) => item && typeof item === "object") as TeamMember[]
    : [];
}

async function loadQueue(supabaseUrl: string, serviceKey: string, dispatchId: string): Promise<Record<string, unknown>> {
  const path = `dispatches/${encodeURIComponent(dispatchId)}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/authenticated/${ACTION_BUCKET}/${path}`, {
    headers: { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey },
  });
  if (!response.ok) throw new Error(`action_queue_read_failed_${response.status}`);
  const parsed = await response.json();
  return objectValue(parsed);
}

async function persistQueue(
  supabaseUrl: string,
  serviceKey: string,
  dispatchId: string,
  queue: Record<string, unknown>,
): Promise<void> {
  const path = `dispatches/${encodeURIComponent(dispatchId)}.json`;
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${ACTION_BUCKET}/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${serviceKey}`,
      apikey: serviceKey,
      "content-type": "application/json",
      "x-upsert": "true",
    },
    body: JSON.stringify(queue),
  });
  if (!response.ok) throw new Error(`action_queue_write_failed_${response.status}`);
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-workload-rebalancer",
      version: SERVICE_VERSION,
      status: "healthy",
      assignment_only: true,
      external_execution_enabled: false,
      readiness_mutation_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }

  let body: Record<string, unknown>;
  try {
    body = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const dispatchId = String(body.dispatch_id || "").trim();
  const apply = body.apply === true;
  const suppliedItems = Array.isArray(body.items)
    ? body.items.filter((item) => item && typeof item === "object") as QueueItem[]
    : [];

  let queue: Record<string, unknown> = {};
  let items = suppliedItems;
  if (!items.length && dispatchId) {
    queue = await loadQueue(supabaseUrl, serviceKey, dispatchId);
    items = Array.isArray(queue.items)
      ? queue.items.filter((item) => item && typeof item === "object") as QueueItem[]
      : [];
  }
  if (!items.length) return jsonResponse(422, { ok: false, error: "items_or_dispatch_id_required" });

  const members = await loadRegistryMembers(supabaseUrl, serviceKey);
  const membersById = new Map(members.map((member) => [memberId(member).toLowerCase(), member]));
  const mutableLoads = new Map<string, number>();
  const nowMs = Date.now();
  const reassignments: Reassignment[] = [];
  const unchangedActionIds: string[] = [];
  const unresolvedActionIds: string[] = [];

  const updatedItems = items.map((item) => {
    const reason = ownerNeedsReassignment(item, membersById, nowMs);
    if (!reason) {
      unchangedActionIds.push(actionId(item));
      return item;
    }

    const previousOwnerId = String(item.owner_id || "").trim();
    const previousOwnerName = String(item.owner_name || "").trim();
    const replacement = chooseReplacement(item, members, mutableLoads, previousOwnerId, nowMs);
    if (!replacement) {
      unresolvedActionIds.push(actionId(item));
      return { ...item, assignment_status: "unassigned", reassignment_reason: reason };
    }

    const reassignment: Reassignment = {
      action_id: actionId(item),
      previous_owner_id: previousOwnerId || null,
      previous_owner_name: previousOwnerName || null,
      owner_id: replacement.id,
      owner_name: String(replacement.member.name || replacement.id),
      routing_reason: replacement.reason,
      reassignment_reason: reason,
      workload_after_assignment: replacement.newLoad,
    };
    reassignments.push(reassignment);
    return {
      ...item,
      assignment_status: "assigned",
      owner_id: reassignment.owner_id,
      owner_name: reassignment.owner_name,
      routing_reason: reassignment.routing_reason,
      reassignment_reason: reassignment.reassignment_reason,
      workload_after_assignment: reassignment.workload_after_assignment,
      reassigned_at: new Date(nowMs).toISOString(),
    };
  });

  let persisted = false;
  if (apply) {
    if (!dispatchId || !Object.keys(queue).length) {
      return jsonResponse(422, { ok: false, error: "dispatch_id_required_to_apply" });
    }
    const updatedQueue = {
      ...queue,
      items: updatedItems,
      workload_rebalanced_at: new Date(nowMs).toISOString(),
      workload_rebalance_summary: {
        reassigned: reassignments.length,
        unchanged: unchangedActionIds.length,
        unresolved: unresolvedActionIds.length,
      },
    };
    await persistQueue(supabaseUrl, serviceKey, dispatchId, updatedQueue);
    persisted = true;
  }

  return jsonResponse(200, {
    ok: true,
    total_items: items.length,
    reassigned_items: reassignments.length,
    unchanged_items: unchangedActionIds.length,
    unresolved_items: unresolvedActionIds.length,
    reassignments,
    unchanged_action_ids: unchangedActionIds,
    unresolved_action_ids: unresolvedActionIds,
    applied: persisted,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    external_action_started: false,
  });
});
