from __future__ import annotations

from copy import deepcopy

from .fixtures import FIXTURE_FAMILY, load_fixture_family
from .mode import HarnessMode
from .report import HarnessReport
from .side_effects import ActionType, SideEffectBus


def run_approval_gate_no_release() -> HarnessReport:
    """Prove each production release gate blocks when one required condition is missing."""
    fixture = load_fixture_family()
    base_deal = fixture["deal"]
    pending_approval = fixture["approval"]
    approved_approval = {**fixture["approval"], "status": "approved", "approved": True}
    bus = SideEffectBus(HarnessMode.PRODUCTION)

    missing_approval_deal = deepcopy(base_deal)
    missing_approval_deal["internal_only"] = False
    missing_approval_deal["external_action_started"] = True
    missing_approval = bus.request(
        ActionType.OFFER_SEND,
        {"probe": "missing_owner_approval"},
        deal=missing_approval_deal,
        owner_approval=pending_approval,
    )

    missing_external_start_deal = deepcopy(base_deal)
    missing_external_start_deal["internal_only"] = False
    missing_external_start_deal["external_action_started"] = False
    missing_external_start = bus.request(
        ActionType.OFFER_SEND,
        {"probe": "missing_external_action_started"},
        deal=missing_external_start_deal,
        owner_approval=approved_approval,
    )

    internal_only_deal = deepcopy(base_deal)
    internal_only_deal["internal_only"] = True
    internal_only_deal["external_action_started"] = True
    internal_only = bus.request(
        ActionType.OFFER_SEND,
        {"probe": "internal_only"},
        deal=internal_only_deal,
        owner_approval=approved_approval,
    )

    records = (missing_approval, missing_external_start, internal_only)
    passed = all(record.decision == "blocked" for record in records) and bus.provider_calls == 0
    return HarnessReport(
        scenario="approval_gate_no_release",
        mode=bus.mode.value,
        fixture_family=FIXTURE_FAMILY,
        verdict="PASS" if passed else "FAIL",
        provider_calls=bus.provider_calls,
        actions=list(bus.records),
        artifacts={
            "release_attempted": True,
            "release_performed": False,
            "probes": [record.to_dict() for record in records],
        },
    )
