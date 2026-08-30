from __future__ import annotations

from cfh_disposition.harness.staging_scenario import run_staging_mode_boundary


def test_staging_allows_only_staging_crm_and_blocks_every_external_action() -> None:
    result = run_staging_mode_boundary()

    assert result["verdict"] == "PASS"
    assert result["staging_executor_calls"] == 1
    assert result["production_executor_calls"] == 0
    assert result["external_actions_started"] == 0
    assert result["bus_executor_calls"] == 1

    crm = result["crm_record"]
    assert crm["action_type"] == "crm.commit"
    assert crm["decision"] == "staging_only"
    assert "staging executor" in crm["reason"]

    blocked = result["blocked_records"]
    assert {record["action_type"] for record in blocked} == {
        "email.send",
        "sms.send",
        "offer.send",
        "contract.send",
        "contract.sign",
        "ads.spend",
        "ads.authorized_scrape",
        "money.move",
    }
    assert all(record["decision"] == "blocked" for record in blocked)
    assert all("Staging mode blocks" in record["reason"] for record in blocked)
