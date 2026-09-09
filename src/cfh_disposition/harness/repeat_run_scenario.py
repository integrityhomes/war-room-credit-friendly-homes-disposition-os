from __future__ import annotations

from copy import deepcopy
from typing import Any

from .fixtures import load_fixture_family
from .runner import run_communications_followup_no_send, run_offer_no_send


def _stable_report(report: dict[str, Any]) -> dict[str, Any]:
    stable = deepcopy(report)
    for key in ("intended_actions", "blocked_actions", "approval_required_actions"):
        for action in stable.get(key, []):
            action.pop("timestamp", None)
    return stable


def run_repeat_run_boundary() -> dict[str, Any]:
    """Prove safe scenario retries do not mutate fixtures or change business outcomes."""
    fixture_before = load_fixture_family()
    offer_first = run_offer_no_send().to_dict()
    offer_second = run_offer_no_send().to_dict()
    comms_first = run_communications_followup_no_send().to_dict()
    comms_second = run_communications_followup_no_send().to_dict()
    fixture_after = load_fixture_family()

    passed = (
        fixture_before == fixture_after
        and _stable_report(offer_first) == _stable_report(offer_second)
        and _stable_report(comms_first) == _stable_report(comms_second)
        and offer_first["provider_calls"] == 0
        and offer_second["provider_calls"] == 0
        and comms_first["provider_calls"] == 0
        and comms_second["provider_calls"] == 0
    )
    return {
        "scenario": "repeat_run_safety",
        "verdict": "PASS" if passed else "FAIL",
        "fixture_unchanged": fixture_before == fixture_after,
        "offer_results_stable": _stable_report(offer_first) == _stable_report(offer_second),
        "communications_results_stable": _stable_report(comms_first) == _stable_report(comms_second),
        "provider_calls": sum(
            report["provider_calls"]
            for report in (offer_first, offer_second, comms_first, comms_second)
        ),
        "cross_process_deduplication_claimed": False,
    }
