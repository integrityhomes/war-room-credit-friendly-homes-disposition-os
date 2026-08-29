const SERVICE_VERSION = "2026-08-29.7";

type Row = Record<string, unknown>;

type ServiceCheck = {
  service: string;
  required: boolean;
};

type SafetyPolicy = {
  healthy: boolean;
  reason: string | null;
};

const SYSTEM_OF_RECORD_ENTITIES = [
  "contacts",
  "properties",
  "deals",
  "activities",
  "communications",
  "tasks",
  "offers",
  "documents",
  "transactions",
] as const;

const REQUIRED_SERVICES: ServiceCheck[] = [
  { service: "commandcore-crm-core", required: true },
  { service: "commandcore-inbound-lead-capture", required: true },
  { service: "commandcore-owner-routing", required: true },
  { service: "commandcore-action-queue", required: true },
  { service: "commandcore-crm-followup-sync", required: true },
  { service: "commandcore-followup-intelligence", required: true },
  { service: "commandcore-stage-intelligence", required: true },
  { service: "commandcore-owner-approval-release", required: true },
  { service: "commandcore-approval-engine", required: true },
  { service: "commandcore-deal-lifecycle-coordinator", required: true },
  { service: "commandcore-deal-lifecycle-readiness", required: true },
  { service: "commandcore-deal-specialist-prep", required: true },
  { service: "commandcore-contract-document-coordinator", required: true },
  { service: "commandcore-executed-contract-handoff", required: true },
  { service: "commandcore-closing-dispo-handoff", required: true },
  { service: "commandcore-deal-completion", required: true },
  { service: "commandcore-adapter-registry", required: true },
  { service: "commandcore-contact-ledger", required: true },
  { service: "commandcore-outbound-prep", required: true },
  { service: "commandcore-communication-gate", required: true },
  { service: "commandcore-execution-readiness", required: true },
  { service: "commandcore-dispatch-worker", required: true },
  { service: "commandcore-deal-flow-orchestrator", required: true },
  { service: "commandcore-workload-balance-advisor", required: true },
  { service: "commandcore-safe-rebalance-apply", required: true },
  { service: "commandcore-auto-rebalance", required: true },
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

async function getServiceHealth(url: string, key: string, service: string): Promise<Row> {
  const response = await fetch(`${url}/functions/v1/${service}`, {
    method: "GET",
    headers: {
      authorization: `Bearer ${key}`,
      "cache-control": "no-cache",
    },
  });
  const parsed = await response.json().catch(() => ({})) as Row;
  return {
    ...parsed,
    http_status: response.status,
    http_ok: response.ok,
  };
}

function evaluateSafetyPolicy(service: string, health: Row): SafetyPolicy {
  if (service === "commandcore-crm-core") {
    const healthy =
      health.migration_safe_external_ids === true &&
      health.destructive_delete_enabled === false &&
      health.external_execution_enabled === false;
    return {
      healthy,
      reason: healthy ? null : "crm_core_integrity_posture_not_verified",
    };
  }

  if (service === "commandcore-inbound-lead-capture") {
    const healthy =
      health.duplicate_safe === true &&
      health.automatic_owner_routing === true &&
      health.external_assignment_override_allowed === false &&
      health.internal_assignment_override_requires_service_role === true &&
      health.external_execution_enabled === false;
    return {
      healthy,
      reason: healthy ? null : "inbound_assignment_boundary_not_verified",
    };
  }

  if (service === "commandcore-auto-rebalance") {
    const healthy =
      health.low_risk_assignment_only === true &&
      health.high_confidence_only === true &&
      health.external_execution_enabled === false &&
      health.readiness_mutation_enabled === false &&
      health.approval_mutation_enabled === false &&
      health.consent_mutation_enabled === false;
    return {
      healthy,
      reason: healthy ? null : "auto_rebalance_safety_posture_not_verified",
    };
  }

  return { healthy: true, reason: null };
}

async function checkService(url: string, key: string, item: ServiceCheck): Promise<Row> {
  const startedAt = Date.now();
  try {
    const parsed = await getServiceHealth(url, key, item.service);
    const endpointHealthy = parsed.http_ok === true && parsed.ok === true;
    const policy = evaluateSafetyPolicy(item.service, parsed);
    const healthy = endpointHealthy && policy.healthy;
    return {
      service: item.service,
      required: item.required,
      healthy,
      health_endpoint_healthy: endpointHealthy,
      safety_policy_healthy: policy.healthy,
      safety_policy_failure: policy.reason,
      http_status: parsed.http_status,
      reported_status: String(parsed.status ?? "").trim() || null,
      version: String(parsed.version ?? "").trim() || null,
      duration_ms: Date.now() - startedAt,
    };
  } catch (error) {
    return {
      service: item.service,
      required: item.required,
      healthy: false,
      health_endpoint_healthy: false,
      safety_policy_healthy: false,
      safety_policy_failure: "health_check_failed",
      error: error instanceof Error ? error.message : "health_check_failed",
      duration_ms: Date.now() - startedAt,
    };
  }
}

async function assessCrmCutover(url: string, key: string): Promise<Row> {
  try {
    const [staging, commit, backup, reconciliation] = await Promise.all([
      getServiceHealth(url, key, "commandcore-crm-import-staging"),
      getServiceHealth(url, key, "commandcore-crm-import-commit"),
      getServiceHealth(url, key, "commandcore-crm-backup"),
      getServiceHealth(url, key, "commandcore-crm-reconciliation"),
    ]);

    const supported = Array.isArray(staging.supported_entities)
      ? staging.supported_entities.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean)
      : [];
    const missing = SYSTEM_OF_RECORD_ENTITIES.filter((entity) => !supported.includes(entity));
    const stagingHealthy = staging.http_ok === true && staging.ok === true;
    const commitHealthy = commit.http_ok === true && commit.ok === true;
    const backupHealthy = backup.http_ok === true && backup.ok === true;
    const reconciliationHealthy = reconciliation.http_ok === true && reconciliation.ok === true;
    const guardedApply =
      commit.signed_preview_required_for_apply === true &&
      commit.pre_apply_backup_required === true &&
      commit.explicit_update_permission_required === true;
    const privateBackup =
      backup.backup_bucket_private_required === true &&
      backup.destructive_cleanup_enabled === false;
    const completeMappingCoverage = missing.length === 0;
    const sourceReconciled = reconciliationHealthy && reconciliation.reconciliation_verified === true;
    const platformReady =
      stagingHealthy &&
      commitHealthy &&
      backupHealthy &&
      reconciliationHealthy &&
      guardedApply &&
      privateBackup &&
      completeMappingCoverage;
    const cutoverReady = platformReady && sourceReconciled;

    const blockers: string[] = [];
    if (!stagingHealthy) blockers.push("crm_import_staging_unhealthy");
    if (!commitHealthy) blockers.push("crm_import_commit_unhealthy");
    if (!backupHealthy) blockers.push("crm_backup_unhealthy");
    if (!reconciliationHealthy) blockers.push("crm_source_reconciliation_unhealthy");
    if (!guardedApply) blockers.push("crm_import_apply_guard_not_verified");
    if (!privateBackup) blockers.push("crm_private_backup_not_verified");
    for (const entity of missing) blockers.push(`migration_mapping_missing:${entity}`);
    if (!sourceReconciled) blockers.push("source_crm_data_reconciliation_not_verified");

    return {
      assessed: true,
      system_of_record_entities: [...SYSTEM_OF_RECORD_ENTITIES],
      migration_supported_entities: supported,
      unsupported_migration_entities: missing,
      complete_mapping_coverage: completeMappingCoverage,
      guarded_apply_verified: guardedApply,
      private_backup_verified: privateBackup,
      reconciliation_service_healthy: reconciliationHealthy,
      migration_platform_ready: platformReady,
      crm_cutover_ready: cutoverReady,
      source_crm_data_reconciliation_verified: sourceReconciled,
      latest_reconciliation_verification_id: reconciliation.latest_verification_id || null,
      latest_reconciliation_verified_at: reconciliation.latest_verified_at || null,
      blockers,
    };
  } catch (error) {
    return {
      assessed: false,
      migration_platform_ready: false,
      crm_cutover_ready: false,
      source_crm_data_reconciliation_verified: false,
      blockers: ["crm_cutover_assessment_unavailable"],
      error: error instanceof Error ? error.message : "crm_cutover_assessment_failed",
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
      crm_cutover_assessment_included: true,
      crm_source_reconciliation_included: true,
      auto_rebalance_chain_included: true,
      safety_posture_assessment_included: true,
      crm_integrity_posture_included: true,
      external_execution_enabled: false,
      destructive_action_enabled: false,
    });
  }
  if (req.method !== "POST") return json(405, { ok: false, error: "method_not_allowed" });
  if (!authed(req)) return json(401, { ok: false, error: "unauthorized" });

  const url = (Deno.env.get("SUPABASE_URL") || "").replace(/\/$/, "");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!url || !key) return json(500, { ok: false, error: "service_not_configured" });

  const [checks, crmCutover] = await Promise.all([
    Promise.all(REQUIRED_SERVICES.map((item) => checkService(url, key, item))),
    assessCrmCutover(url, key),
  ]);
  const failed = checks.filter((item) => item.required === true && item.healthy !== true);
  const safetyFailures = checks.filter((item) => item.required === true && item.safety_policy_healthy !== true);
  const ready = failed.length === 0;

  return json(ready ? 200 : 503, {
    ok: ready,
    launch_ready: ready,
    required_service_count: REQUIRED_SERVICES.length,
    healthy_service_count: checks.filter((item) => item.healthy === true).length,
    failed_required_count: failed.length,
    failed_required_services: failed.map((item) => item.service),
    safety_posture_failure_count: safetyFailures.length,
    safety_posture_failed_services: safetyFailures.map((item) => item.service),
    checks,
    crm_cutover: crmCutover,
    external_action_started: false,
    destructive_action_started: false,
    owner_approval_bypassed: false,
  });
});
