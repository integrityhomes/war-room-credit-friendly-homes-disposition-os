from __future__ import annotations

from cfh_disposition.harness.production_release_scenario import run_production_release_positive_control


def test_production_release_requires_and_honors_all_explicit_gates_with_fake_executor() -> None:
    result = run_production_release_positive_control()

    assert result["verdict"] == "PASS"
    assert result["fake_executor_calls"] == 1
    assert result["real_provider_connected"] is False

    record = result["record"]
    assert record["action_type"] == "offer.send"
    assert record["decision"] == "allowed"
    assert record["external_action_started"] is True
    assert record["approval_present"] is True
    assert record["internal_only"] is False
    assert "Explicit production safety gates passed" in record["reason"]
