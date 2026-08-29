const SERVICE_VERSION = "2026-08-29.1";

type Row = Record<string, unknown>;

type ServiceCheck = {
  service: string;
  required: boolean;
};

const REQUIRED_SERVICES: ServiceCheck[] = [
  { service: "commandcore-crm-core", required: true },
  { service: "commandcore-inbound-lead-capture", required: true },
  { service: "commandcore-owner-routing", required: true },
  { service: "commandcore-followup-intelligence", required: true },
  { service: "commandcore-owner-approval-release", required: true },
  { service: "commandcore-deal-lifecycle-coordinator", required: true },
  { service: "commandcore-deal-lifecycle-readiness", required: true },
  { service: "commandcore-deal-specialist-prep", required: true },
  { service: "commandcore-contract-document-coordinator", required: true },
  { service: "commandcore-executed-contract-handoff", required: true },
  { service: "commandcore-closing-dispo-handoff", required: true },
  { service: "commandcore-deal-completion", required: true },
  { service: "commandcore-deal-flow-orchestrator", required: true },
];

function json(status: number, payload: Row): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
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

async function checkService(url: string, key: string, item: ServiceCheck): Promise<Row> {
  const startedAt = Date.now();
  try {
    const response = await fetch(`${url}/functions/v1/${item.service}`, {
      method: "GET",
      headers: {
        authorization: `Bearer ${key}`,
        "cache-control": "no-cache",
      },
    });
    const parsed = await response.json().catch(() => ({})) as Row;
    const healthy = response.ok && parsed.ok === true;
    return {
      service: item.service,
      required: item.required,
      healthy,
      http_status: response.status,
      reported_status: String(parsed.status ?? "").trim() || null,
      version: String(parsed.version ?? "").trim() || null,
      duration_ms: Date.now() - startedAt,
    };
  } catch (error) {
    return {
      service: item.service,
      required: item.required,
      healthy: false,
      error: error instanceof Error ? error.message : "health_check_failed",
      duration_ms: Date.now() - startedAt,
    };
  }
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return json(200, {
      ok: true,
      service: "commandcore-launch-readiness",
      version: SERVICE_VERSION,
      status: "healthy",
      live_chain_check_requires_authentication: true,
      external_execution_enabled: false,
      destructive_action_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  const checks = await Promise.all(REQUIRED_SERVICES.map((item) => checkService(url, key, item)));
  const failed = checks.filter((item) => item.required === true && item.healthy !== true);
  const ready = failed.length === 0;

  return json(ready ? 200 : 503, {
    ok: ready,
    launch_ready: ready,
    required_service_count: REQUIRED_SERVICES.length,
    healthy_service_count: checks.filter((item) => item.healthy === true).length,
    failed_required_count: failed.length,
    failed_required_services: failed.map((item) => item.service),
    checks,
    external_action_started: false,
    destructive_action_started: false,
    owner_approval_bypassed: false,
  });
});
