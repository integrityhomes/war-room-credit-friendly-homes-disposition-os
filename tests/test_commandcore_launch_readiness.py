from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-launch-readiness/index.ts"
WORKFLOW = ROOT / ".github/workflows/commandcore-launch-readiness.yml"
DEPLOY = ROOT / ".github/workflows/deploy-commandcore-launch-readiness.yml"
CRM_CORE = ROOT / "supabase/functions/commandcore-crm-core/index.ts"
INBOUND = ROOT / "supabase/functions/commandcore-inbound-lead-capture/index.ts"


def test_launch_readiness_checks_full_critical_chain() -> None:
    source = FUNCTION.read_text()
    for service in (
        "commandcore-crm-core",
        "commandcore-inbound-lead-capture",
        "commandcore-owner-routing",
        "commandcore-action-queue",
        "commandcore-crm-followup-sync",
        "commandcore-followup-intelligence",
        "commandcore-stage-intelligence",
        "commandcore-owner-approval-release",
        "commandcore-approval-engine",
        "commandcore-deal-lifecycle-coordinator",
        "commandcore-deal-lifecycle-readiness",
        "commandcore-deal-specialist-prep",
        "commandcore-contract-document-coordinator",
        "commandcore-executed-contract-handoff",
        "commandcore-closing-dispo-handoff",
        "commandcore-deal-completion",
        "commandcore-adapter-registry",
        "commandcore-contact-ledger",
        "commandcore-outbound-prep",
        "commandcore-communication-gate",
        "commandcore-execution-readiness",
        "commandcore-dispatch-worker",
        "commandcore-deal-flow-orchestrator",
        "commandcore-workload-balance-advisor",
        "commandcore-safe-rebalance-apply",
        "commandcore-auto-rebalance",
    ):
        assert service in source
    assert "auto_rebalance_chain_included: true" in source
    assert "safety_posture_assessment_included: true" in source
    assert "crm_integrity_posture_included: true" in source
    assert "owner_approval_release_posture_included: true" in source


def test_launch_readiness_requires_critical_safety_postures() -> None:
    source = FUNCTION.read_text()
    assert "function evaluateSafetyPolicy" in source
    assert 'service === "commandcore-crm-core"' in source
    assert "health.migration_safe_external_ids === true" in source
    assert "health.destructive_delete_enabled === false" in source
    assert 'service === "commandcore-inbound-lead-capture"' in source
    assert "health.duplicate_safe === true" in source
    assert "health.automatic_owner_routing === true" in source
    assert "health.external_assignment_override_allowed === false" in source
    assert "health.internal_assignment_override_requires_service_role === true" in source
    assert 'service === "commandcore-owner-approval-release"' in source
    assert "health.idempotent_release_enabled === true" in source
    assert "health.stable_release_timestamp_enabled === true" in source
    assert "owner_approval_release_idempotency_not_verified" in source
    assert 'service === "commandcore-auto-rebalance"' in source
    assert "health.low_risk_assignment_only === true" in source
    assert "health.high_confidence_only === true" in source
    assert "health.readiness_mutation_enabled === false" in source
    assert "health.approval_mutation_enabled === false" in source
    assert "health.consent_mutation_enabled === false" in source
    assert "safety_posture_failure_count" in source
    assert "safety_posture_failed_services" in source


def test_inbound_retries_use_stable_upsert_identity() -> None:
    crm = CRM_CORE.read_text(encoding="utf-8")
    inbound = INBOUND.read_text(encoding="utf-8")
    assert "function deterministicImportId" in crm
    assert '"x-upsert": "true"' in crm
    assert "migration_safe_external_ids: true" in crm
    for suffix in ("-contact", "-property", "-deal", "-captured"):
        assert f"`${{baseExternal}}{suffix}`" in inbound
    assert "duplicate_safe: true" in inbound


def test_live_chain_check_is_authenticated_and_non_executing() -> None:
    source = FUNCTION.read_text()
    assert "if (!authed(req))" in source
    assert "external_action_started: false" in source
    assert "destructive_action_started: false" in source
    assert "owner_approval_bypassed: false" in source


def test_scheduled_check_fails_closed_when_chain_is_unhealthy() -> None:
    workflow = WORKFLOW.read_text()
    assert 'cron: "42 * * * *"' in workflow
    assert 'assert data.get("launch_ready") is True' in workflow
    assert 'assert data.get("failed_required_count") == 0' in workflow


def test_deploy_verifies_auditor_authenticated_chain_and_safety_posture() -> None:
    deploy = DEPLOY.read_text()
    assert "commandcore-launch-readiness" in deploy
    assert "Verify auditor health" in deploy
    assert "Verify complete CommandCore operating chain" in deploy
    assert "SUPABASE_SERVICE_ROLE_KEY" in deploy
    assert 'assert data.get("safety_posture_assessment_included") is True' in deploy
    assert 'assert data.get("crm_integrity_posture_included") is True' in deploy
    assert 'assert data.get("launch_ready") is True' in deploy
    assert 'assert data.get("failed_required_count") == 0' in deploy
    assert 'assert data.get("safety_posture_failure_count") == 0' in deploy
    assert 'assert data.get("safety_posture_failed_services") == []' in deploy
    assert 'assert data.get("external_action_started") is False' in deploy
    assert 'assert data.get("destructive_action_started") is False' in deploy
    assert 'assert data.get("owner_approval_bypassed") is False' in deploy
