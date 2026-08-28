const DISPATCH_BUCKET = "commandcore-dispatch-queue";
const WORKER_VERSION = "2026-08-27.3";
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

function campaignProperty(queued: Record<string, unknown>): Record<string, unknown> {
  const campaignPayload = queued.campaign_payload && typeof queued.campaign_payload === "object" && !Array.isArray(queued.campaign_payload)
    ? queued.campaign_payload as Record<string, unknown>
    : {};
  return campaignPayload.property && typeof campaignPayload.property === "object" && !Array.isArray(campaignPayload.property)
    ? campaignPayload.property as Record<string, unknown>
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

async function buildWorkOrders(queued: Record<string, unknown>, leadLink: Record<string, unknown> | null) {
  const routes = Array.isArray(queued.routes) ? queued.routes : [];
  const orders: Record<string, unknown>[] = [];
  const leadFormUrl = String(leadLink?.lead_form_url || "").trim();
  const formVersion = String(leadLink?.form_version || "").trim();
  const withLeadLink = (order: Record<string, unknown>, include = true): Record<string, unknown> => include && leadFormUrl
    ? { ...order, lead_form_url: leadFormUrl, lead_form_version: formVersion || null }
    : order;

  for (const item of routes) {
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const route = item as Record<string, unknown>;
    const channelKey = String(route.channel_key || "").trim();
    const routeName = String(route.route || "").trim();

    if (channelKey === "property_page" && routeName === "automatic_ready") {
      orders.push(withLeadLink({ channel_key: channelKey, adapter: "cfh_internal_property_page", state: "confirmed_internal_live", external_action_required: false, external_action_started: false, result_status: "live", note: "Property landing pages are rendered from the approved CFH property record." }));
      continue;
    }

    if (channelKey === "market_seo" && routeName === "automatic_ready") {
      try {
        const result = await runMarketSeoAdapter(queued);
        orders.push(withLeadLink({ channel_key: channelKey, adapter: "cfh_market_seo", state: "confirmed_internal_live", external_action_required: false, external_action_started: false, result_status: "live", seo_record: result.seo_record || null }));
      } catch (error) {
        console.error("CommandCore market SEO adapter failed", error);
        orders.push(withLeadLink({ channel_key: channelKey, adapter: "cfh_market_seo", state: "failed_safe", external_action_required: false, external_action_started: false, result_status: "failed", note: "Market SEO adapter failed; no external action was started." }));
      }
      continue;
    }

    if (routeName === "approval_queue") {
      orders.push(withLeadLink({ channel_key: channelKey, adapter: "approval_gate", state: "awaiting_approval", external_action_required: true, external_action_started: false, result_status: "awaiting_approval" }));
      continue;
    }
    if (routeName === "manual_final_post") {
      orders.push(withLeadLink({ channel_key: channelKey, adapter: "manual_final_post", state: "package_ready_for_human", external_action_required: true, external_action_started: false, result_status: "ready" }));
      continue;
    }
    if (routeName === "blocked") {
      orders.push(withLeadLink({ channel_key: channelKey, adapter: "safety_hold", state: "blocked", external_action_required: false, external_action_started: false, result_status: "blocked" }, false));
      continue;
    }
    orders.push(withLeadLink({ channel_key: channelKey, adapter: "unassigned", state: "review_required", external_action_required: false, external_action_started: false, result_status: "review" }));
  }
  return orders;
}

Deno.serve(async (req) => {
  if (req.method === "GET") return jsonResponse(200, { ok: true, service: "commandcore-dispatch-worker", version: WORKER_VERSION, status: "healthy", external_execution_enabled: false, market_seo_adapter_enabled: true, property_lead_links_enabled: true });
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
    const leadLink = await generatePropertyLeadLink(queued);
    const workOrders = await buildWorkOrders(queued, leadLink);
    const campaignPayload = queued.campaign_payload && typeof queued.campaign_payload === "object" && !Array.isArray(queued.campaign_payload)
      ? queued.campaign_payload as Record<string, unknown>
      : {};
    const enrichedCampaignPayload = leadLink?.lead_form_url
      ? { ...campaignPayload, lead_form_url: leadLink.lead_form_url, lead_form_version: leadLink.form_version || null }
      : campaignPayload;
    const updated = { ...queued, campaign_payload: enrichedCampaignPayload, status: "adapter_work_prepared", worker_version: WORKER_VERSION, worker_processed_at: new Date().toISOString(), property_lead_link: leadLink, work_orders: workOrders, external_action_started: false };
    await writeQueueObject(queueObject, updated);
    return jsonResponse(200, {
      ok: true,
      accepted: true,
      dispatch_id: String(queued.dispatch_id || dispatchId),
      queue_object: queueObject,
      status: "adapter_work_prepared",
      work_order_count: workOrders.length,
      lead_form_url: leadLink?.lead_form_url || null,
      channel_results: workOrders.map((item) => ({ channel_key: item.channel_key, status: item.result_status, lead_form_url: item.lead_form_url || null })),
      external_action_started: false,
    });
  } catch (error) {
    console.error("CommandCore dispatch worker failed", error);
    return jsonResponse(503, { ok: false, error: "dispatch_worker_unavailable", external_action_started: false });
  }
});
