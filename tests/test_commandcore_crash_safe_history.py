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
