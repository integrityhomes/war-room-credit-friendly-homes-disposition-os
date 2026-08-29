const SERVICE_VERSION = "2026-08-29.2";
const MAX_BODY_BYTES = 32 * 1024;

type Row = Record<string, unknown>;

function jsonResponse(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function obj(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const authorization = req.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function links(record: Row): Row {
  return obj(record.links);
}

function isOpen(record: Row): boolean {
  return !new Set(["done", "completed", "closed", "cancelled", "canceled"]).has(text(record.status).toLowerCase());
}

async function crmCall(url: string, key: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) {
    throw new Error(text(parsed.error) || `crm_call_failed_${response.status}`);
  }
  return parsed;
}

async function listEntity(url: string, key: string, entity: string): Promise<Row[]> {
  const result = await crmCall(url, key, { action: "list", entity, limit: 500 });
  return Array.isArray(result.records)
    ? result.records.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Row[]
    : [];
}

async function upsertEntity(url: string, key: string, entity: string, record: Row): Promise<Row> {
  const result = await crmCall(url, key, { action: "upsert", entity, record });
  return obj(result.record);
}

function workMetadata(workType: string): { channel: string; actions: string[]; priority: string } {
  const map: Record<string, { channel: string; actions: string[]; priority: string }> = {
    deal_analysis: { channel: "acquisitions", actions: ["analyze deal"], priority: "medium" },
    prepare_offer: { channel: "acquisitions", actions: ["prepare offer", "owner approval required"], priority: "high" },
    prepare_contract: { channel: "contracts", actions: ["prepare contract package", "owner approval required"], priority: "high" },
    title_closing: { channel: "closing", actions: ["review title and closing requirements"], priority: "high" },
    marketing_dispo: { channel: "disposition", actions: ["prepare marketing and disposition handoff"], priority: "medium" },
  };
  return map[workType] || { channel: "operations", actions: ["review lifecycle work"], priority: "medium" };
}

async function routeTask(url: string, key: string, task: Row, deal: Row | undefined): Promise<Row> {
  const taskId = text(task.id);
  const dealId = text(links(task).deal_id || task.deal_id);
  const workType = text(task.work_type);
  const meta = workMetadata(workType);
  const response = await fetch(`${url}/functions/v1/commandcore-owner-routing`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify({
      items: [{
        action_id: taskId || `${dealId}-${workType}`,
        property_id: text(links(deal || {}).property_id) || null,
        channel_key: meta.channel,
        readiness: "manual",
        reasons: [workType],
        required_actions: meta.actions,
        owner_id: text(deal?.assigned_to) || undefined,
      }],
    }),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) {
    return { status: "unassigned", reason: text(parsed.error) || `routing_failed_${response.status}` };
  }
  const assignments = Array.isArray(parsed.assignments) ? parsed.assignments : [];
  const assignment = assignments.length ? obj(assignments[0]) : {};
  if (!text(assignment.owner_id) && !text(assignment.owner_name)) {
    return { status: "unassigned", reason: "no_available_owner" };
  }
  return {
    status: "assigned",
    owner_id: text(assignment.owner_id) || null,
    owner_name: text(assignment.owner_name) || null,
    routing_reason: text(assignment.routing_reason) || null,
    priority: meta.priority,
  };
}

async function writeRoutingHistory(
  url: string,
  key: string,
  task: Row,
  dealId: string,
  assignedTo: string | null,
  coordinationStatus: string,
  coordinationReason: string | null,
  occurredAt: string,
): Promise<void> {
  const taskId = text(task.id);
  const workType = text(task.work_type);
  const stableKey = taskId || `${dealId}-${workType}`;
  await upsertEntity(url, key, "activities", {
    source: "commandcore-deal-lifecycle-coordinator",
    external_id: `deal-lifecycle-routing-${stableKey}`,
    activity_type: "deal_lifecycle_routed",
    title: "Deal lifecycle work coordinated",
    summary: `${text(task.title) || workType} → ${assignedTo || "needs owner"}`,
    occurred_at: occurredAt,
    details: {
      work_type: workType,
      coordination_status: coordinationStatus,
      coordination_reason: coordinationReason,
      assigned_to: assignedTo,
      approval_bypassed: false,
      external_action_started: false,
    },
    links: { deal_id: dealId || null, task_id: taskId || null },
  });
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-deal-lifecycle-coordinator",
      version: SERVICE_VERSION,
      status: "healthy",
      supported_work_types: ["deal_analysis", "prepare_offer", "prepare_contract", "title_closing", "marketing_dispo"],
      crash_safe_history_enabled: true,
      external_execution_enabled: false,
      approval_bypass_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    return jsonResponse(413, { ok: false, error: "payload_too_large" });
  }
  let body: Row = {};
  try {
    body = JSON.parse(raw || "{}") as Row;
  } catch {
    return jsonResponse(400, { ok: false, error: "invalid_json" });
  }

  const apply = body.apply !== false;
  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  try {
    const [tasks, deals] = await Promise.all([listEntity(url, key, "tasks"), listEntity(url, key, "deals")]);
    const dealById = new Map(deals.map((deal) => [text(deal.id), deal]));
    const candidates = tasks.filter((task) => text(task.task_type) === "deal_lifecycle_request" && isOpen(task));
    const results: Row[] = [];

    for (const task of candidates) {
      const dealId = text(links(task).deal_id || task.deal_id);
      const deal = dealById.get(dealId);
      const alreadyCoordinated = text(task.coordination_status) === "routed" && text(task.assigned_to);
      if (alreadyCoordinated) {
        if (apply) {
          await writeRoutingHistory(
            url,
            key,
            task,
            dealId,
            text(task.assigned_to) || null,
            "routed",
            text(task.coordination_reason) || null,
            text(task.coordinated_at) || new Date().toISOString(),
          );
        }
        results.push({ task_id: text(task.id), deal_id: dealId, status: "already_routed", assigned_to: task.assigned_to });
        continue;
      }

      const routing = await routeTask(url, key, task, deal);
      if (!apply) {
        results.push({ task_id: text(task.id), deal_id: dealId, work_type: task.work_type, preview: routing });
        continue;
      }

      const assignedTo = text(routing.owner_name) || text(routing.owner_id) || text(task.assigned_to) || null;
      const coordinationStatus = text(routing.status) === "assigned" ? "routed" : "needs_owner";
      const coordinationReason = text(routing.routing_reason || routing.reason) || null;
      const coordinatedAt = new Date().toISOString();

      await writeRoutingHistory(
        url,
        key,
        task,
        dealId,
        assignedTo,
        coordinationStatus,
        coordinationReason,
        coordinatedAt,
      );

      const updated = await upsertEntity(url, key, "tasks", {
        ...task,
        assigned_to: assignedTo,
        priority: text(task.priority) || text(routing.priority) || "medium",
        coordination_status: coordinationStatus,
        coordination_reason: coordinationReason,
        coordinated_at: coordinatedAt,
        external_action_started: false,
      });

      results.push({
        task_id: text(updated.id || task.id),
        deal_id: dealId,
        work_type: text(task.work_type),
        status: text(updated.coordination_status),
        assigned_to: assignedTo,
      });
    }

    return jsonResponse(200, {
      ok: true,
      apply,
      candidate_count: candidates.length,
      routed_count: results.filter((item) => item.status === "routed").length,
      needs_owner_count: results.filter((item) => item.status === "needs_owner").length,
      results,
      crash_safe_history_enabled: true,
      approval_changed: false,
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore deal lifecycle coordinator failed", error);
    return jsonResponse(503, {
      ok: false,
      error: error instanceof Error ? error.message : "deal_lifecycle_coordinator_unavailable",
      external_action_started: false,
    });
  }
});
