from __future__ import annotations

from cfh_disposition.harness.fixtures import load_fixture_family
from cfh_disposition.harness.mode import HarnessMode
from cfh_disposition.harness.side_effects import ActionType, SideEffectBus


def test_wrong_deal_or_unscoped_owner_approval_cannot_release_consequential_action() -> None:
    fixture = load_fixture_family()
    calls: list[tuple[str, dict]] = []
    bus = SideEffectBus(
        HarnessMode.PRODUCTION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )
    deal = {**fixture["deal"], "internal_only": False, "external_action_started": True}
    payload = {"deal_id": deal["id"], "fixture_only": True}

    wrong_deal = bus.request(
        ActionType.OFFER_SEND,
        payload,
        deal=deal,
        owner_approval={"status": "approved", "approved": True, "deal_id": "FIXTURE-DEAL-OTHER"},
    )
    missing_scope = bus.request(
        ActionType.OFFER_SEND,
        payload,
        deal=deal,
        owner_approval={"status": "approved", "approved": True},
    )
    matching = bus.request(
        ActionType.OFFER_SEND,
        payload,
        deal=deal,
        owner_approval={"status": "approved", "approved": True, "links": {"deal_id": deal["id"]}},
    )

    assert wrong_deal.decision == "blocked"
    assert wrong_deal.approval_present is False
    assert missing_scope.decision == "blocked"
    assert missing_scope.approval_present is False
    assert matching.decision == "allowed"
    assert matching.approval_present is True
    assert calls == [("offer.send", payload)]
    assert bus.provider_calls == 1
