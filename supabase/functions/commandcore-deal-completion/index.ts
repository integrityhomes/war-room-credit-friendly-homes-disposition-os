const SERVICE_VERSION = "2026-08-29.3";

type Row = Record<string, unknown>;

const FINAL_OUTCOME_TYPES = new Set([
  "disposition_completion",
  "buyer_sale_completion",
  "owner_finance_completion",
  "owner_finance_activation",
]);
const FINAL_OUTCOME_STATUSES = new Set(["completed", "closed", "settled", "activated", "active"]);
const TERMINAL_DEAL_STATUSES = new Set(["completed", "closed", "sold", "cancelled", "canceled", "dead"]);
const COMPLETED_DEAL_STATUSES = new Set(["completed", "closed", "sold"]);
const TERMINAL_TASK_STATUSES = new Set(["done", "completed", "closed", "cancelled", "canceled"]);

function text(value: unknown): string { return String(value ?? "").trim(); }
function obj(value: unknown): Row { return value && typeof value === "object" && !Array.isArray(value) ? value as Row : {}; }
function links(row: Row): Row { return obj(row.links); }
function json(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}
function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let i = 0; i < left.length; i += 1) difference |= left.charCodeAt(i) ^ right.charCodeAt(i);
  return difference === 0;
}
function authed(req: Request): boolean {
  const expected = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const authorization = req.headers.get("authorization") || "";
  const supplied = authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
  return Boolean(expected && supplied && constantTimeEqual(expected, supplied));
}
function effectiveAt(transaction: Row): string {
  return text(transaction.completion_effective_at || transaction.closed_at || transaction.activated_at);
}
function verifiedFinalOutcome(transaction: Row): boolean {
  return FINAL_OUTCOME_TYPES.has(text(transaction.transaction_type).toLowerCase()) &&
    FINAL_OUTCOME_STATUSES.has(text(transaction.status).toLowerCase()) &&
    transaction.completion_verified === true &&
    transaction.buyer_contract_executed === true &&
    Boolean(effectiveAt(transaction));
}
function terminalDeal(deal: Row): boolean {
  return TERMINAL_DEAL_STATUSES.has(text(deal.status || deal.stage).toLowerCase());
}
function completedDeal(deal: Row): boolean {
  return COMPLETED_DEAL_STATUSES.has(text(deal.status || deal.stage).toLowerCase());
}
function openLifecycleTask(task: Row, dealId: string): boolean {
  return text(task.task_type) === "deal_lifecycle_request" &&
    text(links(task).deal_id || task.deal_id) === dealId &&
    !TERMINAL_TASK_STATUSES.has(text(task.status).toLowerCase());
}
async function crmCall(url: string, key: string, payload: Row): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/commandcore-crm-core`, {
    method: "POST",
    headers: { authorization: `Bearer ${key}`, "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) throw new Error(text(parsed.error) || `crm_call_failed_${response.status}`);
  return parsed;
}
async function listEntity(url: string, key: string, entity: string): Promise<Row[]> {
  const result = await crmCall(url, key, { action: "list", entity, limit: 500 });
  return Array.isArray(result.records) ? result.records.filter((item) => item && typeof item === "object" && !Array.isArray(item)) as Row[] : [];
}
async function upsert(url: string, key: string, entity: string, record: Row): Promise<Row> {
  const result = await crmCall(url, key, { action: "upsert", entity, record });
  return obj(result.record);
}

async function writeCompletionHistory(
  url: string,
  key: string,
  transaction: Row,
  dealId: string,
  completedAt: string,
  lifecycleTasksCompleted: number,
): Promise<void> {
  const transactionId = text(transaction.id);
  await upsert(url, key, "activities", {
    source: "commandcore-deal-completion",
    external_id: `deal-completion-${transactionId || dealId}`,
    activity_type: "deal_completed",
    title: "Deal completed from verified final outcome",
    summary: "CommandCore recorded the deal as completed only after explicit verified disposition/owner-finance outcome evidence.",
    occurred_at: completedAt,
    details: {
      transaction_type: text(transaction.transaction_type),
      completion_verified: true,
      buyer_contract_executed: true,
      lifecycle_tasks_completed: lifecycleTasksCompleted,
      marketing_sold_flag_sufficient: false,
      history_preserved: true,
      external_action_started: false,
    },
    links: { deal_id: dealId, transaction_id: transactionId || null },
  });
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return json(200, {
      ok: true,
      service: "commandcore-deal-completion",
      version: SERVICE_VERSION,
      status: "healthy",
      explicit_completion_evidence_required: true,
      marketing_sold_flag_sufficient: false,
      crash_safe_history_enabled: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  try {
    const [transactions, deals, tasks] = await Promise.all([
      listEntity(url, key, "transactions"),
      listEntity(url, key, "deals"),
      listEntity(url, key, "tasks"),
    ]);
    const dealById = new Map(deals.map((deal) => [text(deal.id), deal]));
    const candidates = transactions.filter((transaction) => verifiedFinalOutcome(transaction) && text(transaction.deal_completion_status) !== "released");
    const results: Row[] = [];

    for (const transaction of candidates) {
      const transactionId = text(transaction.id);
      const dealId = text(links(transaction).deal_id || transaction.deal_id);
      if (!dealId) {
        results.push({ transaction_id: transactionId, status: "blocked_missing_deal_link" });
        continue;
      }
      const deal = dealById.get(dealId);
      if (!deal) {
        results.push({ transaction_id: transactionId, deal_id: dealId, status: "blocked_missing_deal" });
        continue;
      }

      const completedAt = effectiveAt(transaction);
      const openTasks = tasks.filter((item) => openLifecycleTask(item, dealId));

      if (terminalDeal(deal)) {
        if (completedDeal(deal)) {
          await writeCompletionHistory(url, key, transaction, dealId, completedAt, openTasks.length);
        }
        await upsert(url, key, "transactions", {
          ...transaction,
          deal_completion_status: "released",
          deal_completion_recorded_at: new Date().toISOString(),
          external_action_started: false,
        });
        results.push({ transaction_id: transactionId, deal_id: dealId, status: "already_terminal" });
        continue;
      }

      await writeCompletionHistory(url, key, transaction, dealId, completedAt, openTasks.length);

      await upsert(url, key, "deals", {
        ...deal,
        status: "completed",
        stage: "completed",
        completed_at: completedAt,
        completion_source: "verified_final_outcome",
        completion_transaction_id: transactionId || null,
        completion_transaction_type: text(transaction.transaction_type) || null,
        external_action_started: false,
      });

      let lifecycleTasksCompleted = 0;
      for (const task of openTasks) {
        await upsert(url, key, "tasks", {
          ...task,
          status: "completed",
          completed_at: completedAt,
          completion_reason: "deal_completed_from_verified_final_outcome",
          external_action_started: false,
        });
        lifecycleTasksCompleted += 1;
      }

      if (lifecycleTasksCompleted !== openTasks.length) {
        await writeCompletionHistory(url, key, transaction, dealId, completedAt, lifecycleTasksCompleted);
      }

      await upsert(url, key, "transactions", {
        ...transaction,
        deal_completion_status: "released",
        deal_completion_recorded_at: new Date().toISOString(),
        external_action_started: false,
      });
      results.push({ transaction_id: transactionId, deal_id: dealId, status: "completed", lifecycle_tasks_completed: lifecycleTasksCompleted });
    }

    return json(200, {
      ok: true,
      candidate_count: candidates.length,
      completed_count: results.filter((item) => item.status === "completed").length,
      results,
      explicit_completion_evidence_required: true,
      marketing_sold_flag_sufficient: false,
      history_preserved: true,
      crash_safe_history_enabled: true,
      external_action_started: false,
    });
  } catch (error) {
    console.error("Deal completion coordinator failed", error);
    return json(503, { ok: false, error: error instanceof Error ? error.message : "deal_completion_unavailable", external_action_started: false });
  }
});
