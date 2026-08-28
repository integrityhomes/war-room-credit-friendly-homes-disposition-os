const SERVICE_VERSION = "2026-08-28.2";

type Row = Record<string, unknown>;

const STAGE_RANK: Record<string, number> = {
  "": 0,
  new: 10,
  new_lead: 10,
  lead: 10,
  contacted: 20,
  follow_up: 25,
  nurture: 25,
  negotiation: 30,
  offer_made: 40,
  under_contract: 50,
  closing: 60,
  closed: 70,
  sold: 70,
};

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

function latestTimestamp(record: Row): number {
  for (const key of ["occurred_at", "completed_at", "created_at", "updated_at"]) {
    const raw = text(record[key]);
    const parsed = Date.parse(raw);
    if (raw && Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function dealLink(record: Row): string {
  const links = obj(record.links);
  return text(record.deal_id || links.deal_id);
}

function normalizedStage(value: unknown): string {
  return text(value).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function rank(stage: string): number {
  return STAGE_RANK[stage] ?? 0;
}

function inferStage(deal: Row, related: Record<string, Row[]>): { stage: string; reason: string; confidence: string } | null {
  const current = normalizedStage(deal.stage || deal.pipeline_stage || deal.status);
  const closed = new Set(["closed", "sold", "dead", "cancelled", "canceled", "lost", "archived"]);
  if (closed.has(current)) return null;

  const documents = related.documents || [];
  const offers = related.offers || [];
  const communications = related.communications || [];
  const activities = related.activities || [];
  const tasks = related.tasks || [];
  const transactions = related.transactions || [];

  if (transactions.length) {
    const transactionText = transactions
      .map((record) => `${text(record.status)} ${text(record.type)} ${text(record.title)}`.toLowerCase())
      .join(" ");
    if (/closing|title|escrow|transaction|settlement/.test(transactionText)) {
      return { stage: "closing", reason: "transaction_or_closing_activity_recorded", confidence: "high" };
    }
  }

  const contractEvidence = documents.some((record) => {
    const joined = `${text(record.type)} ${text(record.name)} ${text(record.title)}`.toLowerCase();
    return joined.includes("contract") && (joined.includes("signed") || joined.includes("executed"));
  });
  if (contractEvidence) {
    return { stage: "under_contract", reason: "signed_or_executed_contract_recorded", confidence: "high" };
  }

  const offerEvidence = offers.some((record) => {
    const status = text(record.status).toLowerCase();
    return !["draft", "void", "withdrawn", "rejected"].includes(status);
  });
  if (offerEvidence) return { stage: "offer_made", reason: "active_offer_recorded", confidence: "high" };

  const recentTouch = [...communications, ...activities].sort((a, b) => latestTimestamp(b) - latestTimestamp(a))[0];
  if (recentTouch) {
    const joined = `${text(recentTouch.type)} ${text(recentTouch.direction)} ${text(recentTouch.status)} ${text(recentTouch.notes)}`.toLowerCase();
    if (/negotiat|counter|price|terms|seller replied|agent replied/.test(joined)) {
      return { stage: "negotiation", reason: "recent_two_way_negotiation_activity", confidence: "medium" };
    }
    if (/contact|call|sms|email|conversation|reply/.test(joined) && ["", "new", "new_lead", "lead"].includes(current)) {
      return { stage: "contacted", reason: "seller_or_agent_contact_activity_recorded", confidence: "medium" };
    }
  }

  const completedFollowup = tasks.some((record) => {
    const status = text(record.status).toLowerCase();
    const title = `${text(record.title)} ${text(record.name)}`.toLowerCase();
    return ["done", "completed", "closed"].includes(status) && title.includes("follow");
  });
  if (completedFollowup && ["", "new", "new_lead", "lead"].includes(current)) {
    return { stage: "contacted", reason: "seller_follow_up_completed", confidence: "medium" };
  }

  return null;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return jsonResponse(200, {
      ok: true,
      service: "commandcore-stage-intelligence",
      version: SERVICE_VERSION,
      status: "healthy",
      automatic_safe_stage_updates: true,
      forward_only_stage_updates: true,
      external_execution_enabled: false,
    });
  }
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return jsonResponse(500, { ok: false, error: "service_not_configured" });

  const entities = ["deals", "documents", "offers", "communications", "activities", "tasks", "transactions"];
  const records: Record<string, Row[]> = {};
  try {
    for (const entity of entities) {
      const result = await callService(url, key, "commandcore-crm-core", { action: "list", entity, limit: 500 });
      records[entity] = Array.isArray(result.records) ? result.records as Row[] : [];
    }
  } catch (error) {
    return jsonResponse(503, { ok: false, error: error instanceof Error ? error.message : "crm_unavailable" });
  }

  const proposals: Row[] = [];
  const applied: Row[] = [];
  const skipped: Row[] = [];

  for (const deal of records.deals || []) {
    const dealId = text(deal.id);
    if (!dealId) continue;
    const related: Record<string, Row[]> = {};
    for (const entity of entities.slice(1)) {
      related[entity] = (records[entity] || []).filter((record) => dealLink(record) === dealId);
    }
    const inference = inferStage(deal, related);
    if (!inference) continue;

    const current = normalizedStage(deal.stage || deal.pipeline_stage || deal.status);
    if (current === inference.stage) continue;
    const proposal = {
      deal_id: dealId,
      from_stage: current || null,
      to_stage: inference.stage,
      reason: inference.reason,
      confidence: inference.confidence,
    };
    proposals.push(proposal);

    if (current && rank(inference.stage) <= rank(current)) {
      skipped.push({ ...proposal, skip_reason: "non_forward_stage_change_blocked" });
      continue;
    }

    const autoSafe = inference.confidence === "high" && ["offer_made", "under_contract", "closing"].includes(inference.stage);
    if (!autoSafe) {
      skipped.push({ ...proposal, skip_reason: "recommendation_only" });
      continue;
    }

    try {
      const updated = {
        ...deal,
        stage: inference.stage,
        stage_intelligence: {
          reason: inference.reason,
          confidence: inference.confidence,
          previous_stage: current || null,
          applied_at: new Date().toISOString(),
        },
      };
      await callService(url, key, "commandcore-crm-core", { action: "upsert", entity: "deals", record: updated });
      applied.push(proposal);
    } catch (error) {
      skipped.push({ ...proposal, skip_reason: error instanceof Error ? error.message : "stage_update_failed" });
    }
  }

  return jsonResponse(200, {
    ok: true,
    proposals_count: proposals.length,
    applied_count: applied.length,
    recommendation_only_count: skipped.filter((item) => item.skip_reason === "recommendation_only").length,
    non_forward_blocked_count: skipped.filter((item) => item.skip_reason === "non_forward_stage_change_blocked").length,
    proposals,
    applied,
    skipped,
    external_action_started: false,
  });
});
