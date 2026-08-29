from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-approval-engine/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-receiver.yml"


def test_approval_engine_reports_idempotent_immutable_evidence_contract() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'const APPROVAL_VERSION = "2026-08-29.2"' in source
    assert "idempotent_approval_enabled: true" in source
    assert "immutable_approval_evidence_enabled: true" in source
    assert "external_execution_enabled: false" in source


def test_recorded_approval_replay_returns_original_evidence_before_new_timestamp() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    replay_guard = 'String(queued.status || "").trim() === "approval_recorded" && existingApproval'
    guard_index = source.index(replay_guard)
    timestamp_index = source.index("const approvedAt = new Date().toISOString()")
    write_index = source.index("await writeQueueObject(queueObject, updated)")
    assert guard_index < timestamp_index < write_index
    replay_section = source[guard_index:timestamp_index]
    assert "idempotent_replay: true" in replay_section
    assert "approval: existingApproval" in replay_section
    assert "Number(existingApproval.released_channels || 0)" in replay_section
    assert "writeQueueObject" not in replay_section


def test_shared_deploy_workflow_validates_and_verifies_approval_engine_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "Check approval engine" in workflow
    assert "deno check supabase/functions/commandcore-approval-engine/index.ts" in workflow
    assert "Verify immutable approval engine health contract" in workflow
    assert '"idempotent_approval_enabled":true' in workflow
    assert '"immutable_approval_evidence_enabled":true' in workflow
