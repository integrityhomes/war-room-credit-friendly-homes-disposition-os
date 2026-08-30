from __future__ import annotations

from typing import Any

from .fixtures import load_fixture_family
from .mode import HarnessMode
from .side_effects import ActionType, SideEffectBus


def run_staging_mode_boundary() -> dict[str, Any]:
    """Prove staging writes only through its staging executor and blocks external actions."""
    fixture = load_fixture_family()
    deal = {**fixture["deal"], "internal_only": False, "external_action_started": True}
    approval = {**fixture["approval"], "status": "approved", "approved": True}
    staging_calls: list[tuple[str, dict[str, Any]]] = []
    production_calls: list[tuple[str, dict[str, Any]]] = []
    bus = SideEffectBus(
        HarnessMode.STAGING,
        staging_executor=lambda action, payload: staging_calls.append((action, payload)),
        production_executor=lambda action, payload: production_calls.append((action, payload)),
    )

    crm = bus.request(
        ActionType.CRM_COMMIT,
        {"target": "staging", "record_id": fixture["deal"]["id"], "fixture_only": True},
        deal=deal,
        owner_approval=approval,
    )
    external_actions = (
        ActionType.EMAIL_SEND,
        ActionType.SMS_SEND,
        ActionType.OFFER_SEND,
        ActionType.CONTRACT_SEND,
        ActionType.CONTRACT_SIGN,
        ActionType.ADS_SPEND,
        ActionType.ADS_AUTHORIZED_SCRAPE,
        ActionType.MONEY_MOVE,
    )
    blocked = [
        bus.request(
            action,
            {"fixture_only": True, "action_under_test": action.value},
            deal=deal,
            owner_approval=approval,
        )
        for action in external_actions
    ]

    passed = (
        crm.decision == "staging_only"
        and staging_calls == [("crm.commit", {"target": "staging", "record_id": fixture["deal"]["id"], "fixture_only": True})]
        and production_calls == []
        and all(record.decision == "blocked" for record in blocked)
        and bus.provider_calls == 1
    )
    return {
        "scenario": "staging_only_no_external",
        "verdict": "PASS" if passed else "FAIL",
        "crm_record": crm.to_dict(),
        "blocked_records": [record.to_dict() for record in blocked],
        "staging_executor_calls": len(staging_calls),
        "production_executor_calls": len(production_calls),
        "external_actions_started": 0,
        "bus_executor_calls": bus.provider_calls,
    }
