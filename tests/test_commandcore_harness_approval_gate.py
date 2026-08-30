from __future__ import annotations

from cfh_disposition.harness.approval_gate import run_approval_gate_no_release


def test_approval_gate_no_release_blocks_every_unsafe_probe() -> None:
    report = run_approval_gate_no_release()
    data = report.to_dict()

    assert report.verdict == "PASS"
    assert report.mode == "production"
    assert report.provider_calls == 0
    assert data["artifacts"]["release_attempted"] is True
    assert data["artifacts"]["release_performed"] is False
    assert len(data["blocked_actions"]) == 3

    reasons = {action["payload_summary"]["probe"]: action["reason"] for action in data["blocked_actions"]}
    assert "Owner approval is required" in reasons["missing_owner_approval"]
    assert "external_action_started is not explicitly true" in reasons["missing_external_action_started"]
    assert "internal_only" in reasons["internal_only"]
