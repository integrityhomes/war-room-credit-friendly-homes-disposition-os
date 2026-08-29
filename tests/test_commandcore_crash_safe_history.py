from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_lifecycle_routing_history_is_stable_and_written_before_task_state():
    source = _source("supabase/functions/commandcore-deal-lifecycle-coordinator/index.ts")
    assert "crash_safe_history_enabled: true" in source
    assert "external_id: `deal-lifecycle-routing-${stableKey}`" in source
    history_call = source.index("await writeRoutingHistory(\n        url")
    task_write = source.index('const updated = await upsertEntity(url, key, "tasks"')
    assert history_call < task_write


def test_lifecycle_readiness_history_uses_transition_identity_before_task_state():
    source = _source("supabase/functions/commandcore-deal-lifecycle-readiness/index.ts")
    assert "crash_safe_history_enabled: true" in source
    assert "external_id: `deal-lifecycle-readiness-${stableKey}-${transitionFrom}-to-${status}`" in source
    history_write = source.index('await upsertEntity(url, key, "activities"')
    task_write = source.index('await upsertEntity(url, key, "tasks"')
    assert history_write < task_write


def test_deal_completion_history_is_stable_and_written_before_terminal_state():
    source = _source("supabase/functions/commandcore-deal-completion/index.ts")
    assert "crash_safe_history_enabled: true" in source
    assert "external_id: `deal-completion-${transactionId || dealId}`" in source
    history_call = source.index("await writeCompletionHistory(url, key, transaction, dealId, completedAt, openTasks.length);")
    deal_write = source.index('await upsert(url, key, "deals"')
    assert history_call < deal_write


def test_existing_verified_handoffs_keep_deterministic_history_ids():
    executed = _source("supabase/functions/commandcore-executed-contract-handoff/index.ts")
    closing = _source("supabase/functions/commandcore-closing-dispo-handoff/index.ts")
    assert "external_id: `executed-contract-handoff-${documentId}`" in executed
    assert "external_id: `closing-dispo-handoff-${transactionId}`" in closing


def test_launch_readiness_requires_crash_safe_history_posture():
    source = _source("supabase/functions/commandcore-launch-readiness/index.ts")
    for service in (
        "commandcore-deal-lifecycle-coordinator",
        "commandcore-deal-lifecycle-readiness",
        "commandcore-deal-completion",
    ):
        assert f'"{service}"' in source
    assert "CRASH_SAFE_HISTORY_SERVICES.has(service)" in source
    assert "health.crash_safe_history_enabled === true" in source
    assert 'reason: healthy ? null : "crash_safe_history_posture_not_verified"' in source
    assert "crash_safe_history_posture_included: true" in source


def test_launch_readiness_deploy_verifier_retries_503_and_reports_safe_diagnostics():
    workflow = _source(".github/workflows/deploy-commandcore-launch-readiness.yml")
    assert 'assert data.get("crash_safe_history_posture_included") is True' in workflow
    assert "for attempt in $(seq 1 12); do" in workflow
    assert "-o response.json" in workflow
    assert "-w '%{http_code}'" in workflow
    assert 'if [ "$HTTP_STATUS" = "200" ]' in workflow
    assert "failed_required_services=" in workflow
    assert "safety_posture_failed_services=" in workflow
    assert "crm_cutover_blockers=" in workflow


def test_deal_completion_deploy_verifies_exact_crash_safe_contract():
    workflow = _source(".github/workflows/deploy-commandcore-deal-completion.yml")
    assert '.github/workflows/deploy-commandcore-deal-completion.yml' in workflow
    assert "deno check supabase/functions/commandcore-deal-completion/index.ts" in workflow
    assert 'assert data.get("version") == "2026-08-29.3"' in workflow
    assert 'assert data.get("crash_safe_history_enabled") is True' in workflow
    assert 'assert data.get("external_execution_enabled") is False' in workflow


def test_readiness_rechecks_when_crash_safe_services_or_deploy_contract_change():
    workflow = _source(".github/workflows/deploy-commandcore-launch-readiness.yml")
    for path in (
        "supabase/functions/commandcore-deal-lifecycle-coordinator/**",
        "supabase/functions/commandcore-deal-lifecycle-readiness/**",
        "supabase/functions/commandcore-deal-completion/**",
        ".github/workflows/deploy-commandcore-deal-completion.yml",
    ):
        assert path in workflow
