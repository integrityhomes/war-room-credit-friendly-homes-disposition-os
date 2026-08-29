const SERVICE_VERSION = "2026-08-29.1";

type Row = Record<string, unknown>;

function text(value: unknown): string {
  return String(value ?? "").trim();
}

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

async function invokeStep(url: string, key: string, service: string, body: Row = {}): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/${service}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${key}`,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  if (!response.ok || parsed.ok !== true) {
    throw new Error(`${service}:${text(parsed.error) || `http_${response.status}`}`);
  }
  return parsed;
}

Deno.serve(async (req) => {
  if (req.method === "GET") {
    return json(200, {
      ok: true,
      service: "commandcore-deal-flow-orchestrator",
      version: SERVICE_VERSION,
      status: "healthy",
      external_execution_enabled: false,
      consequential_approval_bypass_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  try {
    const release = await invokeStep(url, key, "commandcore-owner-approval-release");
    const coordinate = await invokeStep(url, key, "commandcore-deal-lifecycle-coordinator");
    const readiness = await invokeStep(url, key, "commandcore-deal-lifecycle-readiness");
    const specialistPrep = await invokeStep(url, key, "commandcore-deal-specialist-prep", { apply: true });

    return json(200, {
      ok: true,
      steps: {
        owner_approval_release: release,
        lifecycle_coordination: coordinate,
        lifecycle_readiness: readiness,
        specialist_prep: specialistPrep,
      },
      released_count: release.released_count ?? 0,
      coordinated_count: coordinate.coordinated_count ?? coordinate.updated_count ?? 0,
      ready_count: readiness.ready_count ?? 0,
      prepared_count: specialistPrep.prepared_count ?? 0,
      external_action_started: false,
      owner_approval_bypassed: false,
      legal_terms_generated: false,
    });
  } catch (error) {
    console.error("CommandCore deal flow orchestrator failed", error);
    return json(503, {
      ok: false,
      error: error instanceof Error ? error.message : "deal_flow_orchestrator_unavailable",
      external_action_started: false,
      owner_approval_bypassed: false,
    });
  }
});
