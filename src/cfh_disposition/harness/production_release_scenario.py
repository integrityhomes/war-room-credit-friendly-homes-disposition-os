from __future__ import annotations

from typing import Any

from .fixtures import load_fixture_family
from .mode import HarnessMode
from .side_effects import ActionType, SideEffectBus


def run_production_release_positive_control() -> dict[str, Any]:
    """Prove the bus releases only when every production gate is explicitly satisfied."""
    fixture = load_fixture_family()
    calls: list[tuple[str, dict[str, Any]]] = []
    bus = SideEffectBus(
        HarnessMode.PRODUCTION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )
    deal = {**fixture["deal"], "internal_only": False, "external_action_started": True}
    approval = {**fixture["approval"], "status": "approved", "approved": True}
    payload = {
        "deal_id": deal["id"],
        "to": "fixture-recipient@example.invalid",
        "offer_amount": 28000,
        "fixture_only": True,
    }

    record = bus.request(
        ActionType.OFFER_SEND,
        payload,
        deal=deal,
        owner_approval=approval,
    )
    passed = (
        record.decision == "allowed"
        and record.external_action_started is True
        and record.approval_present is True
        and calls == [("offer.send", payload)]
        and bus.provider_calls == 1
    )
    return {
        "scenario": "production_release_positive_control",
        "verdict": "PASS" if passed else "FAIL",
        "record": record.to_dict(),
        "fake_executor_calls": len(calls),
        "real_provider_connected": False,
    }
