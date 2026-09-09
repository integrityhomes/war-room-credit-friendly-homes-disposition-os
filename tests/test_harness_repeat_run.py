from __future__ import annotations

from cfh_disposition.harness.repeat_run_scenario import run_repeat_run_boundary


def test_repeat_runs_keep_fixture_and_business_results_stable_without_provider_calls() -> None:
    result = run_repeat_run_boundary()

    assert result["verdict"] == "PASS"
    assert result["fixture_unchanged"] is True
    assert result["offer_results_stable"] is True
    assert result["communications_results_stable"] is True
    assert result["provider_calls"] == 0
    assert result["cross_process_deduplication_claimed"] is False
