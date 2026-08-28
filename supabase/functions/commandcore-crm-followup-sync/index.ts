const SERVICE_VERSION = "2026-08-28.1";

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

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const auth = req.headers.get("authorization") || "";
  const supplied = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function obj(value: unknown): Row {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
}

function dueNow(value: unknown): boolean {
  const due = text(value);
  if (!due) return false;
  const parsed = Date.parse(due.length === 10 ? `${due}T23:59:59Z` : due);
  return Number.isFinite(parsed) && parsed <= Date.now();
}

async function callService(url: string, key: string, service: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/${service}`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `${service}_failed_${response.status}`);
  return parsed;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-crm-followup-sync",
      version: SERVICE_VERSION,
      status: "healthy",
      action_queue_sync: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  let tasks: Row[] = [];
  try {
    const result = await callService(url, key, "commandcore-crm-core", { action: "list", entity: "tasks", limit: 500 });
    tasks = Array.isArray(result.records) ? result.records as Row[] : [];
  } catch (error) {
    return jsonResponse(503, { ok: false, error: error instanceof Error ? error.message : "crm_tasks_unavailable" });
  }

  const open = tasks.filter((task) => {
    const status = text(task.status).toLowerCase();
    return !["done", "completed", "closed", "cancelled", "canceled"].includes(status) && dueNow(task.due_date || task.due_at);
  });

  const synced: Row[] = [];
  const failed: Row[] = [];
  for (const task of open.slice(0, 100)) {
    const links = obj(task.links);
    const taskId = text(task.id);
    const dealId = text(links.deal_id || task.deal_id);
    const propertyId = text(links.property_id || task.property_id);
    const owner = text(task.assigned_to || task.owner_name || task.owner_id);
    try {
      await callService(url, key, "commandcore-action-queue", {
        dispatch: {
          dispatch_id: `crm-followup-${taskId}`,
          property_id: propertyId || null,
          deal_owner: owner || null,
          work_orders: [{
            channel_key: "crm-follow-up",
            readiness: "MANUAL",
            readiness_reasons: ["crm_follow_up"],
            marketing_package: {
              task_id: taskId,
              deal_id: dealId || null,
              title: text(task.title || task.name || "CRM follow-up"),
              due_date: text(task.due_date || task.due_at) || null,
            },
          }],
        },
      });
      synced.push({ task_id: taskId, deal_id: dealId || null });
    } catch (error) {
      failed.push({ task_id: taskId, error: error instanceof Error ? error.message : "queue_sync_failed" });
    }
  }

  return jsonResponse(200, {
    ok: failed.length === 0,
    due_followups: open.length,
    synced_count: synced.length,
    failed_count: failed.length,
    synced,
    failed,
    external_action_started: false,
  });
});
