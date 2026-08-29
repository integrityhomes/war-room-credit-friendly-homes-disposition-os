from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-execution-readiness/index.ts"
OUTBOUND = ROOT / "supabase/functions/commandcore-outbound-prep/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-receiver.yml"


def test_execution_readiness_reports_verified_handoff_contract() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'const SERVICE_VERSION = "2026-08-29.2"' in source
    assert "outbound_handoff_contract_enabled: true" in source
    assert "connection_evidence_fail_closed: true" in source
    assert "external_execution_enabled: false" in source


def test_execution_readiness_consumes_outbound_prep_connection_fields() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    outbound = OUTBOUND.read_text(encoding="utf-8")
    for field in (
        "connection_ready",
        "connection_state",
        "connection_health",
        "execution_permitted",
        "connection_identity",
    ):
        assert field in outbound
        assert f"handoff.{field}" in source
    assert "obj(handoff.connection)" not in source


def test_connection_required_channels_fail_closed_without_verified_identity() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'reasons.push("connection_connected")' in source
    assert 'reasons.push("connection_healthy")' in source
    assert 'reasons.push("execution_permission")' in source
    assert 'reasons.push("connection_verified")' in source
    assert 'reasons.push("channel_identity")' in source
    assert 'const readiness = unique.length ? "HOLD" : "READY"' in source


def test_shared_deploy_validates_and_verifies_execution_readiness_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Check execution readiness" in workflow
    assert "deno check supabase/functions/commandcore-execution-readiness/index.ts" in workflow
    assert "Verify execution readiness handoff health contract" in workflow
    assert '"outbound_handoff_contract_enabled":true' in workflow
    assert '"connection_evidence_fail_closed":true' in workflow
