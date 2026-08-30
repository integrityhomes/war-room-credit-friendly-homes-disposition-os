from __future__ import annotations

from cfh_disposition.commandcore_offer_workspace_ui import (
    activity_record,
    analysis_status,
    build_input,
    default_values,
    offer_record,
)


def result(best_exit: str = "Slow Flip", grade: str = "B") -> dict:
    return {
        "best_exit": best_exit,
        "grade": grade,
        "best": {
            "offer_to_send": 28000,
            "first_offer": 28000,
            "max_offer": 32000,
            "resale_to_slow_flipper": 54000,
            "estimated_fee_at_ask": 12500,
        },
    }


def test_deal_and_property_prefill_use_real_records() -> None:
    values = default_values(
        {"asking_price": 30000, "notes": "Seller wants a quick close."},
        {
            "address": "123 Main St",
            "city": "Decatur",
            "state": "IL",
            "bedrooms": 3,
            "bathrooms": 1,
            "square_feet": 1100,
            "market_rent": 1200,
            "arv": 90000,
        },
    )

    assert values["address"] == "123 Main St"
    assert values["market"] == "Decatur, IL"
    assert values["asking_price"] == 30000
    assert values["rent"] == 1200
    assert values["arv"] == 90000
    assert values["beds"] == 3
    assert values["sqft"] == 1100


def test_unverified_rent_stays_explicit_in_engine_input() -> None:
    engine_input = build_input(
        {
            "address": "123 Main St",
            "exit_mode": "Slow Flip Only",
            "asking_price": 30000,
            "rent": 1200,
            "rent_confidence": "Weak",
            "rent_verification_needed": "Yes",
        }
    )

    assert engine_input.rent_verification_needed == "Yes"
    assert engine_input.rent_confidence == "Weak"


def test_internal_analysis_does_not_enter_owner_queue_automatically() -> None:
    assert analysis_status(result()) == "analysis_complete"
    assert analysis_status(result("Needs Human Review", "Review")) == "analysis_needs_review"

    record = offer_record(deal_id="deal-1", result=result(), values={"address": "123 Main St"})
    assert record["status"] == "analysis_complete"
    assert record["terms"]["internal_only"] is True
    assert record["external_action_started"] is False


def test_explicit_approval_request_updates_same_offer_record() -> None:
    record = offer_record(
        deal_id="deal-1",
        result=result(),
        values={"address": "123 Main St"},
        status="draft_pending_owner_approval",
        existing_id="offer-123",
    )

    assert record["id"] == "offer-123"
    assert record["status"] == "draft_pending_owner_approval"
    assert record["links"]["deal_id"] == "deal-1"
    assert record["external_action_started"] is False


def test_activity_history_is_internal_and_deal_linked() -> None:
    activity = activity_record("deal-1", result())

    assert activity["activity_type"] == "deal_analysis"
    assert activity["links"]["deal_id"] == "deal-1"
    assert activity["details"]["external_action_started"] is False
    assert "$28,000" in activity["summary"]
    assert "$32,000" in activity["summary"]
