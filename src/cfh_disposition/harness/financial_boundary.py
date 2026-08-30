from __future__ import annotations

from typing import Any

from .fixtures import FIXTURE_FAMILY, load_fixture_family
from .mode import HarnessMode
from .report import HarnessReport
from .side_effects import ActionType, SideEffectBus


def run_money_spend_no_release() -> HarnessReport:
    """Prove financial side effects remain blocked behind production gates."""
    fixture = load_fixture_family()
    deal = dict(fixture["deal"])
    deal["internal_only"] = False
    deal["external_action_started"] = False
    approved_looking = {
        "id": "FIXTURE-APPROVAL-FINANCIAL-0001",
        "status": "approved",
        "approved": True,
        "internal_only": True,
    }
    calls: list[tuple[str, dict[str, Any]]] = []
    bus = SideEffectBus(
        HarnessMode.PRODUCTION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )

    ad_spend = bus.request(
        ActionType.ADS_SPEND,
        {
            "campaign_id": "FIXTURE-CAMPAIGN-0001",
            "amount": 250,
            "currency": "USD",
        },
        deal=deal,
        owner_approval=approved_looking,
    )
    money_move = bus.request(
        ActionType.MONEY_MOVE,
        {
            "transaction_id": "FIXTURE-TRANSACTION-0001",
            "amount": 1000,
            "currency": "USD",
        },
        deal=deal,
        owner_approval=approved_looking,
    )

    passed = (
        ad_spend.decision == "blocked"
        and money_move.decision == "blocked"
        and bus.provider_calls == 0
        and calls == []
    )
    return HarnessReport(
        scenario="money_spend_no_release",
        mode=bus.mode.value,
        fixture_family=FIXTURE_FAMILY,
        verdict="PASS" if passed else "FAIL",
        provider_calls=bus.provider_calls,
        actions=list(bus.records),
        artifacts={
            "approved_looking_record": approved_looking,
            "financial_provider_calls": len(calls),
            "ad_spend_performed": False,
            "money_move_performed": False,
        },
    )
