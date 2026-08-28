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

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => text(item)).filter(Boolean) : [];
}

async function loadMembers(supabaseUrl: string, serviceKey: string): Promise<RecordValue[]> {
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-team-registry`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({ action: "list" }),
  });
  if (!response.ok) throw new Error("team_registry_unavailable");
  const parsed = await response.json() as RecordValue;
  return Array.isArray(parsed.members)
    ? parsed.members.filter((item) => item && typeof item === "object") as RecordValue[]
    : [];
}

async function loadCoverage(supabaseUrl: string, serviceKey: string): Promise<RecordValue[]> {
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-team-coverage`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) throw new Error("team_coverage_unavailable");
  const parsed = await response.json() as RecordValue;
  return Array.isArray(parsed.coverage)
    ? parsed.coverage.filter((item) => item && typeof item === "object") as RecordValue[]
    : [];
}

function chooseBackup(owner: RecordValue, members: RecordValue[], coverage: RecordValue[]): RecordValue | null {
  const backupIds = list(owner.backup_owner_ids).map((id) => id.toLowerCase());
  if (!backupIds.length) return null;
  const coverageById = new Map(coverage.map((item) => [text(item.id).toLowerCase(), item]));
  for (const backupId of backupIds) {
    const member = members.find((item) => text(item.id).toLowerCase() === backupId);
    if (!member || member.active === false) continue;
    const current = coverageById.get(backupId);
    if (current?.available !== true) continue;
    const currentLoad = Number(member.current_load || 0);
    const maxLoad = Number(member.max_load || 20);
    if (Number.isFinite(currentLoad) && Number.isFinite(maxLoad) && currentLoad >= maxLoad) continue;
    return member;
  }
  return null;
}

async function triggerRebalance(
  supabaseUrl: string,
  serviceKey: string,
  dispatchId: string,
): Promise<RecordValue> {
  const response = await fetch(`${supabaseUrl}/functions/v1/commandcore-workload-rebalancer`, {
    method: "POST",
    headers: { Authorization: `Bearer ${serviceKey}`, "content-type": "application/json" },
    body: JSON.stringify({ dispatch_id: dispatchId, apply: true }),
  });
  if (!response.ok) throw new Error(`workload_rebalancer_failed_${response.status}`);
  return await response.json() as RecordValue;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-coverage-escalation",
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

  let body: RecordValue;
  try {
    body = JSON.parse(raw || "{}") as RecordValue;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const ownerId = text(body.owner_id);
  const dispatchId = text(body.dispatch_id);
  const handoffStatus = text(body.handoff_status).toLowerCase();
  const apply = body.apply === true;
  if (!ownerId) return jsonResponse(422, { ok: false, error: "owner_id_required" });
  if (!["missed", "overdue", "critical"].includes(handoffStatus)) {
    return jsonResponse(200, {
      ok: true,
      escalation_required: false,
      reason: "handoff_not_missed",
      applied: false,
      external_action_started: false,
    });
  }

  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const [members, coverage] = await Promise.all([
    loadMembers(supabaseUrl, serviceKey),
    loadCoverage(supabaseUrl, serviceKey),
  ]);
  const owner = members.find((item) => text(item.id).toLowerCase() === ownerId.toLowerCase());
  if (!owner) return jsonResponse(404, { ok: false, error: "owner_not_found" });

  const backup = chooseBackup(owner, members, coverage);
  if (!backup) {
    return jsonResponse(200, {
      ok: true,
      escalation_required: true,
      backup_available: false,
      recommended_action: "Manager review required: no eligible designated backup is available.",
      applied: false,
      external_action_started: false,
    });
  }

  let rebalance: RecordValue | null = null;
  if (apply) {
    if (!dispatchId) return jsonResponse(422, { ok: false, error: "dispatch_id_required_to_apply" });
    rebalance = await triggerRebalance(supabaseUrl, serviceKey, dispatchId);
  }

  return jsonResponse(200, {
    ok: true,
    escalation_required: true,
    backup_available: true,
    missed_owner_id: ownerId,
    backup_owner_id: text(backup.id),
    backup_owner_name: text(backup.name || backup.id),
    recommended_action: apply ? "Coverage reassignment requested." : "Route uncovered work to designated backup.",
    applied: apply,
    rebalance,
    assignment_only: true,
    readiness_changed: false,
    approval_changed: false,
    consent_changed: false,
    budget_changed: false,
    external_action_started: false,
  });
});
