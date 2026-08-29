const DISPATCH_BUCKET = "commandcore-dispatch-queue";
const WORKER_VERSION = "2026-08-29.1";
const MAX_BODY_BYTES = 16 * 1024;

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function bearerToken(req: Request): string {
  const auth = req.headers.get("authorization") || "";
  return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

function isAuthenticated(req: Request): boolean {
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  const supplied = bearerToken(req);
  return Boolean(serviceRoleKey && supplied && constantTimeEqual(serviceRoleKey, supplied));
}

function storageHeaders(serviceRoleKey: string): HeadersInit {
  return { authorization: `Bearer ${serviceRoleKey}`, apikey: serviceRoleKey, "content-type": "application/json" };
}

function safePart(value: unknown): string {
  return String(value ?? "").trim().replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 120);
}

function campaignPayload(queued: Record<string, unknown>): Record<string, unknown> {
  return queued.campaign_payload && typeof queued.campaign_payload === "object" && !Array.isArray(queued.campaign_payload)
    ? queued.campaign_payload as Record<string, unknown>
    : {};
}

function campaignProperty(queued: Record<string, unknown>): Record<string, unknown> {
  const payload = campaignPayload(queued);
  return payload.property && typeof payload.property === "object" && !Array.isArray(payload.property)
    ? payload.property as Record<string, unknown>
    : {};
}

function campaignGates(queued: Record<string, unknown>): Record<string, unknown> {
  const payload = campaignPayload(queued);
  return payload.execution_gates && typeof payload.execution_gates === "object" && !Array.isArray(payload.execution_gates)
    ? payload.execution_gates as Record<string, unknown>
    : {};
}

async function readQueueObject(queueObject: string): Promise<Record<string, unknown>> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("worker_storage_not_configured");
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${DISPATCH_BUCKET}/${queueObject}`, { method: "GET", headers: storageHeaders(serviceRoleKey) });
  if (!response.ok) throw new Error(`queue_read_failed_${response.status}`);
  const parsed = await response.json();
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("queue_payload_invalid");
  return parsed as Record<string, unknown>;
}

async function writeQueueObject(queueObject: string, payload: Record<string, unknown>): Promise<void> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error("worker_storage_not_configured");
  const response = await fetch(`${supabaseUrl}/storage/v1/object/${DISPATCH_BUCKET}/${queueObject}`, {
    method: "POST",
    headers: { ...storageHeaders(serviceRoleKey), "x-upsert": "true" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`queue_update_failed_${response.status}`);
}

async function callInternalFunction(name: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const supabaseUrl = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceRoleKey) throw new Error(`${name}_not_configured`);
  const response = await fetch(`${supabaseUrl}/functions/v1/${name}`, {
    method: "POST",
    headers: { authorization: `Bearer ${serviceRoleKey}`, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${name}_failed_${response.status}`);
  const result = await response.json();
  if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error(`${name}_invalid_response`);
  return result as Record<string, unknown>;
}

async function runMarketSeoAdapter(queued: Record<string, unknown>): Promise<Record<string, unknown>> {
  return await callInternalFunction("commandcore-market-seo", { property: campaignProperty(queued) });
}

async function generatePropertyLeadLink(queued: Record<string, unknown>): Promise<Record<string, unknown> | null> {
  try {
    return await callInternalFunction("commandcore-property-link", { property: campaignProperty(queued) });
  } catch (error) {
    console.error("CommandCore property link generation failed", error);
    return null;
  }
}

async function generateMarketingPackages(queued: Record<string, unknown>, leadLink: Record<string, unknown> | null): Promise<Record<string, unknown> | null> {
  try {
    const payload = campaignPayload(queued);
    return await callInternalFunction("commandcore-marketing-copy", {
      ...payload,
      property: campaignProperty(queued),
      lead_form_url: leadLink?.lead_form_url || payload.lead_form_url || "",
    });
  } catch (error) {
    console.error("CommandCore marketing copy generation failed", error);
    return null;
  }
}

function marketingPackageFor(marketing: Record<string, unknown> | null, channelKey: string): Record<string, unknown> | null {
  const packages = Array.isArray(marketing?.packages) ? marketing?.packages : [];
  for (const item of packages) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    if (String(row.channel_key || "").trim() === channelKey) return row;
  }
  return null;
}

const OUTBOUND_CHANNELS = new Set([
  "facebook_marketplace", "facebook_groups", "facebook_page", "instagram", "tiktok", "youtube",
  "blog", "market_seo", "email", "sms", "reactivation", "meta_ads", "google_ads",
]);

async function attachOutboundHandoffs(workOrders: Record<string, unknown>[]): Promise<Record<string, unknown>[]> {
  const prepared: Record<string, unknown>[] = [];
  for (const order of workOrders) {
    const channelKey = String(order.channel_key || "").trim();
    const blocked = String(order.result_status || "").trim() === "blocked" || String(order.state || "").trim() === "blocked";
    if (!OUTBOUND_CHANNELS.has(channelKey) || blocked) {
      prepared.push(order);
      continue;
    }
    try {
      const result = await callInternalFunction("commandcore-outbound-prep", { work_order: order });
      const handoff = result.handoff && typeof result.handoff === "object" && !Array.isArray(result.handoff)
        ? result.handoff as Record<string, unknown>
        : null;
      prepared.push(handoff ? { ...order, outbound_handoff: handoff, outbound_handoff_ready: true } : { ...order, outbound_handoff_ready: false });
    } catch (error) {
      console.error(`CommandCore outbound prep failed for ${channelKey}`, error);
      prepared.push({ ...order, outbound_handoff_ready: false, outbound_handoff_error: "preparation_failed", external_action_started: false });
    }
  }
  return prepared;
}

async function attachReadinessDecisions(workOrders: Record<string, unknown>[], gates: Record<string, unknown>): Promise<Record<string, unknown>[]> {
  const decided: Record<string, unknown>[] = [];
  for (const order of workOrders) {
    const channelKey = String(order.channel_key || "").trim();
    const blocked = String(order.result_status || "").trim() === "blocked" || String(order.state || "").trim() === "blocked";
    if (blocked) {
      decided.push({ ...order, execution_readiness: "BLOCKED", readiness_reasons: ["channel_blocked"], readiness_checked: true });
      continue;
    }
    if (order.external_action_required === false && String(order.result_status || "").trim() === "live") {
      decided.push({ ...order, execution_readiness: "READY", readiness_reasons: ["internal_no_external_action"], readiness_checked: true });
      continue;
    }
    if (!order.outbound_handoff_ready) {
      decided.push({ ...order, execution_readiness: "HOLD", readiness_reasons: ["outbound_handoff_not_ready"], readiness_checked: true });
      continue;
    }
    try {
      const result = await callInternalFunction("commandcore-execution-readiness", { work_order: order, gates });
      const readiness = String(result.readiness || "HOLD").trim().toUpperCase();
      const reasons = Array.isArray(result.reasons) ? result.reasons.map((item) => String(item).trim()).filter(Boolean) : ["readiness_reason_unavailable"];
      decided.push({ ...order, execution_readiness: readiness, readiness_reasons: reasons, readiness_checked: true, readiness_required_gates: Array.isArray(result.required_gates) ? result.required_gates : [] });
    } catch (error) {
      console.error(`CommandCore readiness check failed for ${channelKey}`, error);
      decided.push({ ...order, execution_readiness: "HOLD", readiness_reasons: ["readiness_engine_unavailable"], readiness_checked: false, external_action_started: false });
    }
  }
  return decided;
}

async function generateActionQueue(dispatchId: string, propertyId: string, workOrders: Record<string, unknown>[]): Promise<Record<string, unknown> | null> {
  try {
    const result = await callInternalFunction("commandcore-action-queue", {
      dispatch: {
        dispatch_id: dispatchId,
        property_id: propertyId || null,
        work_orders: workOrders,
      },
    });
    return result.queue && typeof result.queue === "object" && !Array.isArray(result.queue)
      ? result.queue as Record<string, unknown>
      : null;
  } catch (error) {
    console.error("CommandCore action queue generation failed", error);
    return null;
  }
}

async function buildWorkOrders(queued: Record<string, unknown>, leadLink: Record<string, unknown> | null, marketing: Record<string, unknown> | null) {
  const routes = Array.isArray(queued.routes) ? queued.routes : [];
  const orders: Record<string, unknown>[] = [];
  const leadFormUrl = String(leadLink?.lead_form_url || "").trim();
  const formVersion = String(leadLink?.form_version || "").trim();
  const enrich = (order: Record<string, unknown>, channelKey: string, includeLeadLink = true, includeCopy = true): Record<string, unknown> => {
    let enriched = includeLeadLink && leadFormUrl ? { ...order, lead_form_url: leadFormUrl, lead_form_version: formVersion || null } : { ...order };
    const copyPackage = includeCopy ? marketingPackageFor(marketing, channelKey) : null;
    if (copyPackage) enriched = { ...enriched, marketing_package: copyPackage, copy_ready: true };
    return enriched;
  };

  for (const item of routes) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const route = item as Record<string, unknown>;
    const channelKey = String(route.channel_key || "").trim();
    const routeName = String(route.route || "").trim();

    if (channelKey === "property_page" && routeName === "automatic_ready") {
      orders.push(enrich({ channel_key: channelKey, adapter: "cfh_internal_property_page", state: "confirmed_internal_live", external_action_required: false, external_action_started: false, result_status: "live", note: "Property landing pages are rendered from the approved CFH property record." }, channelKey, true, false));
      continue;
    }

    if (channelKey === "market_seo" && routeName === "automatic_ready") {
      try {
        const result = await runMarketSeoAdapter(queued);
        orders.push(enrich({ channel_key: channelKey, adapter: "cfh_market_seo", state: "confirmed_internal_live", external_action_required: false, external_action_started: false, result_status: "live", seo_record: result.seo_record || null }, channelKey));
      } catch (error) {
        console.error("CommandCore market SEO adapter failed", error);
        orders.push(enrich({ channel_key: channelKey, adapter: "cfh_market_seo", state: "failed_safe", external_action_required: false, external_action_started: false, result_status: "failed", note: "Market SEO adapter failed; no external action was started." }, channelKey));
      }
      continue;
    }

    if (routeName === "approval_queue") {
      orders.push(enrich({ channel_key: channelKey, adapter: "approval_gate", state: "awaiting_approval", external_action_required: true, external_action_started: false, result_status: "awaiting_approval" }, channelKey));
      continue;
    }
    if (routeName === "manual_final_post") {
      orders.push(enrich({ channel_key: channelKey, adapter: "manual_final_post", state: "package_ready_for_human", external_action_required: true, external_action_started: false, result_status: "ready", human_final_post_required: true }, channelKey));
      continue;
    }
    if (routeName === "blocked") {
      orders.push(enrich({ channel_key: channelKey, adapter: "safety_hold", state: "blocked", external_action_required: false, external_action_started: false, result_status: "blocked" }, channelKey, false, false));
      continue;
    }
    orders.push(enrich({ channel_key: channelKey, adapter: "unassigned", state: "review_required", external_action_required: false, external_action_started: false, result_status: "review" }, channelKey));
  }
  return orders;
}

function existingWorkOrders(queued: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(queued.work_orders)
    ? queued.work_orders.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item))
    : [];
}

function existingReplayResponse(queued: Record<string, unknown>, queueObject: string, dispatchId: string): Record<string, unknown> {
  const workOrders = existingWorkOrders(queued);
  const payload = campaignPayload(queued);
  const marketing = queued.marketing_copy_result && typeof queued.marketing_copy_result === "object" && !Array.isArray(queued.marketing_copy_result)
    ? queued.marketing_copy_result as Record<string, unknown>
    : null;
  return {
    ok: true,
    accepted: true,
    idempotent_replay: true,
    state_preserved: true,
    dispatch_id: String(queued.dispatch_id || dispatchId),
    queue_object: queueObject,
    status: String(queued.status || ""),
    worker_processed_at: queued.worker_processed_at || null,
    work_order_count: workOrders.length,
    outbound_handoff_count: Number(queued.outbound_handoff_count || 0),
    readiness_counts: queued.readiness_counts || {},
    action_queue_ready: queued.action_queue_ready === true,
    action_queue_summary: queued.action_queue_summary || null,
    lead_form_url: payload.lead_form_url || null,
    marketing_package_count: Array.isArray(marketing?.packages) ? marketing.packages.length : 0,
    approval: queued.approval || null,
    channel_results: workOrders.map((item) => ({ channel_key: item.channel_key, status: item.result_status, state: item.state, readiness: item.execution_readiness, readiness_reasons: item.readiness_reasons || [], lead_form_url: item.lead_form_url || null, copy_ready: Boolean(item.copy_ready), outbound_handoff_ready: Boolean(item.outbound_handoff_ready) })),
    external_action_started: queued.external_action_started === true,
  };
}

Deno.serve(async (req) => {
  if (req.method === "GET") return jsonResponse(200, { ok: true, service: "commandcore-dispatch-worker", version: WORKER_VERSION, status: "healthy", external_execution_enabled: false, market_seo_adapter_enabled: true, property_lead_links_enabled: true, marketing_copy_packages_enabled: true, outbound_handoff_preparation_enabled: true, execution_readiness_enabled: true, action_queue_enabled: true, idempotent_dispatch_processing_enabled: true, approval_state_preservation_enabled: true });
  if (req.method !== "POST") return jsonResponse(405, { ok: false, error: "method_not_allowed" });
  if (!isAuthenticated(req)) return jsonResponse(401, { ok: false, error: "unauthorized" });

  const raw = await req.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) return jsonResponse(413, { ok: false, error: "payload_too_large" });

  let body: Record<string, unknown>;
  try { body = JSON.parse(raw) as Record<string, unknown>; } catch { return jsonResponse(400, { ok: false, error: "invalid_json" }); }

  const dispatchId = safePart(body.dispatch_id);
  const propertyId = safePart(body.property_id);
  const queueObject = safePart(body.queue_object) ? String(body.queue_object) : dispatchId && propertyId ? `dispatches/${propertyId}/${dispatchId}.json` : "";
  if (!queueObject.startsWith("dispatches/") || queueObject.includes("..")) return jsonResponse(422, { ok: false, error: "invalid_queue_object" });

  try {
    const queued = await readQueueObject(queueObject);
    const queuedStatus = String(queued.status || "").trim();
    if (queuedStatus === "action_queue_generated" || queuedStatus === "approval_recorded") {
      return jsonResponse(200, existingReplayResponse(queued, queueObject, dispatchId));
    }

    const resolvedDispatchId = safePart(queued.dispatch_id || dispatchId);
    const resolvedPropertyId = safePart(queued.property_id || propertyId);
    const leadLink = await generatePropertyLeadLink(queued);
    const marketing = await generateMarketingPackages(queued, leadLink);
    const baseWorkOrders = await buildWorkOrders(queued, leadLink, marketing);
    const handedOffWorkOrders = await attachOutboundHandoffs(baseWorkOrders);
    const workOrders = await attachReadinessDecisions(handedOffWorkOrders, campaignGates(queued));
    const actionQueue = await generateActionQueue(resolvedDispatchId, resolvedPropertyId, workOrders);
    const payload = campaignPayload(queued);
    const enrichedCampaignPayload = {
      ...payload,
      ...(leadLink?.lead_form_url ? { lead_form_url: leadLink.lead_form_url, lead_form_version: leadLink.form_version || null } : {}),
      ...(marketing?.packages ? { marketing_packages: marketing.packages } : {}),
    };
    const handoffCount = workOrders.filter((item) => Boolean(item.outbound_handoff_ready)).length;
    const readinessCounts = workOrders.reduce((acc: Record<string, number>, item) => {
      const key = String(item.execution_readiness || "HOLD").toUpperCase();
      acc[key] = (acc[key] || 0) + 1;
      return acc;
    }, {});
    const actionQueueSummary = actionQueue?.summary && typeof actionQueue.summary === "object" && !Array.isArray(actionQueue.summary)
      ? actionQueue.summary as Record<string, unknown>
      : null;
    const updated = {
      ...queued,
      campaign_payload: enrichedCampaignPayload,
      status: "action_queue_generated",
      worker_version: WORKER_VERSION,
      worker_processed_at: new Date().toISOString(),
      property_lead_link: leadLink,
      marketing_copy_result: marketing,
      work_orders: workOrders,
      outbound_handoff_count: handoffCount,
      readiness_counts: readinessCounts,
      action_queue: actionQueue,
      action_queue_ready: Boolean(actionQueue),
      action_queue_summary: actionQueueSummary,
      external_action_started: false,
    };
    await writeQueueObject(queueObject, updated);
    return jsonResponse(200, {
      ok: true,
      accepted: true,
      idempotent_replay: false,
      state_preserved: true,
      dispatch_id: String(queued.dispatch_id || dispatchId),
      queue_object: queueObject,
      status: "action_queue_generated",
      work_order_count: workOrders.length,
      outbound_handoff_count: handoffCount,
      readiness_counts: readinessCounts,
      action_queue_ready: Boolean(actionQueue),
      action_queue_summary: actionQueueSummary,
      lead_form_url: leadLink?.lead_form_url || null,
      marketing_package_count: Array.isArray(marketing?.packages) ? marketing?.packages.length : 0,
      channel_results: workOrders.map((item) => ({ channel_key: item.channel_key, status: item.result_status, readiness: item.execution_readiness, readiness_reasons: item.readiness_reasons || [], lead_form_url: item.lead_form_url || null, copy_ready: Boolean(item.copy_ready), outbound_handoff_ready: Boolean(item.outbound_handoff_ready) })),
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore dispatch worker failed", error);
    return jsonResponse(503, { ok: false, error: "dispatch_worker_unavailable", external_action_started: false });
  }
});