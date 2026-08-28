const SERVICE_VERSION = "2026-08-28.1";

type Row = Record<string, unknown>;

type Rule = {
  days: number;
  title: string;
  priority: string;
  reason: string;
};

const CLOSED_STAGES = new Set([
  "closed",
  "sold",
  "dead",
  "lost",
  "cancelled",
  "canceled",
  "archived",
]);

const RULES: Array<{ terms: string[]; rule: Rule }> = [
  { terms: ["new", "new lead", "lead in"], rule: { days: 1, title: "First seller follow-up", priority: "high", reason: "new_lead" } },
  { terms: ["contacted", "working", "qualified"], rule: { days: 2, title: "Seller follow-up", priority: "high", reason: "active_seller" } },
  { terms: ["appointment", "walkthrough", "inspection"], rule: { days: 1, title: "Appointment follow-up", priority: "high", reason: "appointment" } },
  { terms: ["offer prep", "offer ready", "offer sent", "offered"], rule: { days: 2, title: "Offer follow-up", priority: "high", reason: "offer" } },
  { terms: ["negotiation", "negotiating", "counter"], rule: { days: 2, title: "Negotiation follow-up", priority: "high", reason: "negotiation" } },
  { terms: ["follow up", "follow-up", "nurture", "long term"], rule: { days: 7, title: "Seller nurture follow-up", priority: "medium", reason: "nurture" } },
  { terms: ["contract pending", "contract out", "signature"], rule: { days: 1, title: "Contract status follow-up", priority: "high", reason: "contract_pending" } },
  { terms: ["under contract", "closing", "title"], rule: { days: 3, title: "Transaction status follow-up", priority: "medium", reason: "transaction" } },
];

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
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const auth = req.headers.get("authorization") || "";
  const supplied = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}

function normalizedStage(deal: Row): string {
  return text(deal.stage || deal.pipeline_stage || deal.status).toLowerCase().replace(/[_-]+/g, " ");
}

function ruleFor(stage: string): Rule | null {
  if (!stage || CLOSED_STAGES.has(stage)) return null;
  for (const entry of RULES) {
    if (entry.terms.some((term) => stage.includes(term))) return entry.rule;
  }
  return { days: 3, title: "Seller follow-up", priority: "medium", reason: "active_deal_default" };
}

function isOpen(task: Row): boolean {
  const status = text(task.status).toLowerCase();
  return !["done", "completed", "closed", "cancelled", "canceled"].includes(status);
}

function linkedDealId(record: Row): string {
  const links = obj(record.links);
  return text(links.deal_id || record.deal_id);
}

function dueDate(days: number): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function safeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, "-").slice(0, 120);
}

async function callService(url: string, key: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `crm_core_failed_${response.status}`);
  return parsed;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-followup-intelligence",
      version: SERVICE_VERSION,
      status: "healthy",
      automatic_internal_followups: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  let deals: Row[] = [];
  let tasks: Row[] = [];
  try {
    const [dealResult, taskResult] = await Promise.all([
      callService(url, key, { action: "list", entity: "deals", limit: 500 }),
      callService(url, key, { action: "list", entity: "tasks", limit: 500 }),
    ]);
    deals = Array.isArray(dealResult.records) ? dealResult.records as Row[] : [];
    tasks = Array.isArray(taskResult.records) ? taskResult.records as Row[] : [];
  } catch (error) {
    return jsonResponse(503, { ok: false, error: error instanceof Error ? error.message : "crm_unavailable" });
  }

  const openByDeal = new Set(
    tasks.filter(isOpen).map(linkedDealId).filter(Boolean),
  );
  const created: Row[] = [];
  const skipped: Row[] = [];
  const failed: Row[] = [];
  const today = new Date().toISOString().slice(0, 10);

  for (const deal of deals.slice(0, 500)) {
    const dealId = text(deal.id);
    if (!dealId) continue;
    const stage = normalizedStage(deal);
    const rule = ruleFor(stage);
    if (!rule) {
      skipped.push({ deal_id: dealId, reason: "closed_or_no_stage" });
      continue;
    }
    if (openByDeal.has(dealId)) {
      skipped.push({ deal_id: dealId, reason: "open_followup_exists" });
      continue;
    }

    const links = obj(deal.links);
    const taskId = safeId(`auto-followup-${dealId}-${today}`);
    const task: Row = {
      id: taskId,
      title: rule.title,
      task_type: "seller_follow_up",
      status: "open",
      priority: rule.priority,
      due_date: dueDate(rule.days),
      assigned_to: text(deal.assigned_to || deal.owner_name || deal.owner_id) || null,
      source: "commandcore-followup-intelligence",
      automation_reason: rule.reason,
      pipeline_stage_at_creation: stage,
      auto_created: true,
      links: {
        deal_id: dealId,
        contact_id: text(links.contact_id || deal.contact_id) || null,
        property_id: text(links.property_id || deal.property_id) || null,
      },
    };

    try {
      await callService(url, key, { action: "upsert", entity: "tasks", record: task });
      created.push({ deal_id: dealId, task_id: taskId, due_date: task.due_date, reason: rule.reason });
      openByDeal.add(dealId);
    } catch (error) {
      failed.push({ deal_id: dealId, error: error instanceof Error ? error.message : "task_create_failed" });
    }
  }

  return jsonResponse(200, {
    ok: failed.length === 0,
    deals_scanned: deals.length,
    created_count: created.length,
    skipped_count: skipped.length,
    failed_count: failed.length,
    created,
    skipped,
    failed,
    external_action_started: false,
  });
});
