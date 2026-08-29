from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-launch-readiness/index.ts"
WORKFLOW = ROOT / ".github/workflows/commandcore-launch-readiness.yml"
DEPLOY = ROOT / ".github/workflows/deploy-commandcore-launch-readiness.yml"


def test_launch_readiness_checks_full_critical_chain() -> None:
    source = FUNCTION.read_text()
    for service in (
        "commandcore-crm-core",
        "commandcore-inbound-lead-capture",
        "commandcore-owner-routing",
        "commandcore-followup-intelligence",
        "commandcore-owner-approval-release",
        "commandcore-deal-lifecycle-coordinator",
        "commandcore-deal-lifecycle-readiness",
        "commandcore-deal-specialist-prep",
        "commandcore-contract-document-coordinator",
        "commandcore-executed-contract-handoff",
        "commandcore-closing-dispo-handoff",
        "commandcore-deal-completion",
        "commandcore-deal-flow-orchestrator",
    ):
        assert service in source


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
    deploy = DEPLOY.read_text()
    assert "commandcore-launch-readiness" in deploy
    assert "Verify auditor health" in deploy
