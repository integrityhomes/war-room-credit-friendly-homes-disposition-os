from __future__ import annotations

from typing import Any

from .fixtures import load_fixture_family
from .mode import HarnessMode
from .side_effects import ActionType, SideEffectBus


def run_authorized_scrape_boundary() -> dict[str, Any]:
    """Prove authenticated scraping cannot start outside explicit production release."""
    fixture = load_fixture_family()
    base_deal = fixture["deal"]
    approved = {**fixture["approval"], "status": "approved", "approved": True}
    payload = {
        "platform": "FIXTURE-AD-PLATFORM",
        "purpose": "fixture campaign performance inspection",
        "credential_use_required": True,
        "fixture_only": True,
    }

    production_bus = SideEffectBus(HarnessMode.PRODUCTION)
    missing_release = production_bus.request(
        ActionType.ADS_AUTHORIZED_SCRAPE,
        payload,
        deal={**base_deal, "internal_only": False, "external_action_started": False},
        owner_approval=approved,
    )
    missing_approval = production_bus.request(
        ActionType.ADS_AUTHORIZED_SCRAPE,
        payload,
        deal={**base_deal, "internal_only": False, "external_action_started": True},
        owner_approval={**fixture["approval"], "status": "pending", "approved": False},
    )

    calls: list[tuple[str, dict[str, Any]]] = []
    simulation_bus = SideEffectBus(
        HarnessMode.SIMULATION,
        production_executor=lambda action, body: calls.append((action, body)),
    )
    simulation = simulation_bus.request(
        ActionType.ADS_AUTHORIZED_SCRAPE,
        payload,
        deal={**base_deal, "internal_only": False, "external_action_started": True},
        owner_approval=approved,
    )

    passed = (
        missing_release.decision == "blocked"
        and missing_approval.decision == "blocked"
        and simulation.decision == "blocked"
        and production_bus.provider_calls == 0
        and simulation_bus.provider_calls == 0
        and calls == []
    )
    return {
        "scenario": "authorized_scrape_no_auth",
        "verdict": "PASS" if passed else "FAIL",
        "production_gate_records": [record.to_dict() for record in production_bus.records],
        "simulation_record": simulation.to_dict(),
        "credential_provider_calls": len(calls),
        "provider_calls": production_bus.provider_calls + simulation_bus.provider_calls,
        "authenticated_session_started": False,
    }
