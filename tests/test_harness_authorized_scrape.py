from __future__ import annotations

from cfh_disposition.harness.authorized_scrape_scenario import run_authorized_scrape_boundary


def test_authorized_scrape_requires_release_and_approval_and_simulation_never_authenticates() -> None:
    result = run_authorized_scrape_boundary()

    assert result["verdict"] == "PASS"
    assert result["provider_calls"] == 0
    assert result["credential_provider_calls"] == 0
    assert result["authenticated_session_started"] is False

    records = result["production_gate_records"]
    assert records[0]["decision"] == "blocked"
    assert records[0]["external_action_started"] is False
    assert "external_action_started" in records[0]["reason"]

    assert records[1]["decision"] == "blocked"
    assert records[1]["approval_present"] is False
    assert "Owner approval" in records[1]["reason"]

    simulation = result["simulation_record"]
    assert simulation["decision"] == "blocked"
    assert simulation["approval_present"] is True
    assert simulation["external_action_started"] is True
    assert "Simulation mode" in simulation["reason"]
