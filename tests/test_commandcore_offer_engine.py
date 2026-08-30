from __future__ import annotations

from cfh_disposition.commandcore_offer_engine import (
    OfferAssumptions,
    OfferDealInput,
    analyze_deal,
    calc_slow_flip,
    calc_wholesale,
)


def deal(**overrides) -> OfferDealInput:
    values = {
        "address": "123 Test St",
        "market": "Central IL",
        "lead_type": "Agent",
        "exit_mode": "Auto",
        "asking_price": 30000,
        "rent": 1200,
        "beds": 3,
        "baths": 1,
        "sqft": 1000,
        "taxes": 1200,
        "status": "Active",
        "occupancy": "Vacant",
        "livable": "Yes",
        "days_on_market": 20,
        "notes": "",
        "arv": 100000,
        "repairs": 10000,
        "rent_source": "Verified comps",
        "rent_confidence": "Strong",
        "rent_verification_needed": "No",
    }
    values.update(overrides)
    return OfferDealInput(**values)


def test_wholesale_math_matches_offer_engine_rules() -> None:
    result = calc_wholesale(deal(), OfferAssumptions())

    assert result["buyer_target"] == 60000
    assert result["max_offer"] == 48500
    assert result["target_offer_high"] == 41225
    assert result["first_offer"] == 37102.5
    assert result["offer_to_send"] == 30000


def test_slow_flip_normal_cap_and_opening_offer_are_preserved() -> None:
    result = calc_slow_flip(deal(arv=0, repairs=0), OfferAssumptions())

    assert result["rent_formula_max_offer_before_cap"] == 42500
    assert result["max_offer"] == 32000
    assert result["first_offer"] == 28000
    assert result["offer_to_send"] == 28000


def test_unverified_rent_blocks_clean_slow_flip_exit() -> None:
    result = analyze_deal(
        deal(
            exit_mode="Slow Flip Only",
            arv=0,
            repairs=0,
            rent_confidence="Weak",
            rent_verification_needed="Yes",
        )
    )

    assert result["slow_flip"]["rent_verification_needed"] == "Yes"
    assert result["best_exit"] == "Needs Human Review"


def test_market_slow_flip_max_is_enforced_below_normal_cap() -> None:
    assumptions = OfferAssumptions(slow_flip_max_buy_price=25000, slow_flip_max_source="Market Rule")
    result = calc_slow_flip(deal(asking_price=30000, arv=0, repairs=0), assumptions)

    assert result["max_offer"] == 25000
    assert result["first_offer"] == 21000
    assert result["above_slow_flip_max_buy_price"] is True


def test_auto_mode_can_choose_verified_slow_flip() -> None:
    result = analyze_deal(deal(arv=100000, repairs=10000))

    assert result["best_exit"] == "Slow Flip"
    assert result["best"]["max_offer"] == 32000
