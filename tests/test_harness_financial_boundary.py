from __future__ import annotations

from cfh_disposition.harness.financial_boundary import run_money_spend_no_release
from cfh_disposition.harness.mode import HarnessMode
from cfh_disposition.harness.side_effects import ActionType, SideEffectBus


def test_money_spend_scenario_blocks_approved_looking_requests_without_external_start() -> None:
    data = run_money_spend_no_release().to_dict()

    assert data["verdict"] == "PASS"
    assert data["mode"] == "production"
    assert data["provider_calls"] == 0
    assert data["artifacts"]["financial_provider_calls"] == 0
    assert data["artifacts"]["ad_spend_performed"] is False
    assert data["artifacts"]["money_move_performed"] is False
    blocked = {action["action_type"] for action in data["blocked_actions"]}
    assert {"ads.spend", "money.move"}.issubset(blocked)
    assert all(action["external_action_started"] is False for action in data["blocked_actions"])


def test_simulation_never_calls_financial_executor_even_with_all_release_flags_true() -> None:
    calls: list[tuple[str, dict]] = []
    bus = SideEffectBus(
        HarnessMode.SIMULATION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )
    deal = {
        "id": "FIXTURE-DEAL-FINANCE-0001",
        "internal_only": False,
        "external_action_started": True,
    }
    approval = {"status": "approved", "approved": True}

    spend = bus.request(ActionType.ADS_SPEND, {"amount": 250}, deal=deal, owner_approval=approval)
    move = bus.request(ActionType.MONEY_MOVE, {"amount": 1000}, deal=deal, owner_approval=approval)

    assert spend.decision == "blocked"
    assert move.decision == "blocked"
    assert bus.provider_calls == 0
    assert calls == []
