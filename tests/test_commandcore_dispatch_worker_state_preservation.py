from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-dispatch-worker/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-receiver.yml"


def test_dispatch_worker_reports_state_preservation_contract() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'const WORKER_VERSION = "2026-08-29.1"' in source
    assert "idempotent_dispatch_processing_enabled: true" in source
    assert "approval_state_preservation_enabled: true" in source
    assert "external_execution_enabled: false" in source


def test_dispatch_worker_replay_guard_precedes_all_regeneration_calls() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    guard = 'queuedStatus === "action_queue_generated" || queuedStatus === "approval_recorded"'
    guard_index = source.index(guard)
    lead_link_index = source.index("const leadLink = await generatePropertyLeadLink(queued)")
    marketing_index = source.index("const marketing = await generateMarketingPackages(queued, leadLink)")
    work_order_index = source.index("const baseWorkOrders = await buildWorkOrders(queued, leadLink, marketing)")
    write_index = source.index("await writeQueueObject(queueObject, updated)")
    assert guard_index < lead_link_index < marketing_index < work_order_index < write_index
    replay_section = source[guard_index:lead_link_index]
    assert "existingReplayResponse" in replay_section
    assert "writeQueueObject" not in replay_section


def test_approval_recorded_dispatch_cannot_be_rolled_back_to_awaiting_approval() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'queuedStatus === "approval_recorded"' in source
    assert "state_preserved: true" in source
    assert "approval: queued.approval || null" in source
    assert "idempotent_replay: true" in source


def test_shared_deploy_validates_and_verifies_dispatch_worker_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Check dispatch worker" in workflow
    assert "deno check supabase/functions/commandcore-dispatch-worker/index.ts" in workflow
    assert "Verify dispatch worker state-preservation health contract" in workflow
    assert '"idempotent_dispatch_processing_enabled":true' in workflow
    assert '"approval_state_preservation_enabled":true' in workflow
