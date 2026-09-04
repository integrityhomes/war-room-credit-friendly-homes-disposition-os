from __future__ import annotations

from cfh_disposition.harness.mode import HarnessMode
from cfh_disposition.harness.side_effects import REDACTED, ActionType, SideEffectBus


def test_report_redacts_nested_secrets_but_executor_receives_original_payload() -> None:
    calls: list[tuple[str, dict]] = []
    bus = SideEffectBus(
        HarnessMode.PRODUCTION,
        production_executor=lambda action, payload: calls.append((action, payload)),
    )
    deal = {"id": "FIXTURE-DEAL", "internal_only": False, "external_action_started": True}
    approval = {"status": "approved", "approved": True, "deal_id": deal["id"]}
    payload = {
        "to": "fixture@example.invalid",
        "access_token": "fixture-access-token",
        "nested": {
            "api_key": "fixture-key",
            "routing_number": "000000000",
            "safe_field": "visible",
        },
        "items": [{"password": "fixture-password"}],
    }

    record = bus.request(ActionType.EMAIL_SEND, payload, deal=deal, owner_approval=approval)

    assert record.decision == "allowed"
    assert record.payload_summary["access_token"] == REDACTED
    assert record.payload_summary["nested"]["api_key"] == REDACTED
    assert record.payload_summary["nested"]["routing_number"] == REDACTED
    assert record.payload_summary["nested"]["safe_field"] == "visible"
    assert record.payload_summary["items"][0]["password"] == REDACTED
    assert calls[0][1] == payload
