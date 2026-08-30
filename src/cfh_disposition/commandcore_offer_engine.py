from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class OfferAssumptions:
    """Stable offer rules shared by the standalone Offer Engine and CommandCore."""

    min_assignment_fee: float = 10000
    exception_assignment_fee: float = 5000
    slow_flip_rent_multiple: float = 45
    close_title_buffer: float = 1500
    target_offer_discount: float = 0.85
    wholesale_buyer_percent_arv: float = 0.70
    wholesale_buyer_percent_source: str = "Market Default"
    wholesale_buyer_percent_range: str = ""
    wholesale_buyer_percent_reason: str = ""
    market_liquidity_tier: str = ""
    market_wholesale_buyer_percent: float = 0.70
    slow_flip_max_offer_cap: float = 32000
    slow_flip_first_offer_gap: float = 4000
    slow_flip_lead_search_max: float = 0
    slow_flip_lead_search_source: str = "Market Default"
    above_slow_flip_lead_search_range: bool = False
    inside_slow_flip_lead_search_range: bool = False
    slow_flip_max_buy_price: float = 0
    slow_flip_max_source: str = "Market Default"
    above_slow_flip_max_buy_price: bool = False


@dataclass
class OfferDealInput:
    address: str
    market: str
    lead_type: str
    exit_mode: str
    asking_price: float
    rent: float
    beds: float
    baths: float
    sqft: float
    taxes: float
    status: str
    occupancy: str
    livable: str
    days_on_market: int
    notes: str
    arv: float = 0
    repairs: float = 0
    rent_source: str = "Missing / RentCast unavailable"
    rent_confidence: str = "Weak"
    rent_verification_needed: str = "Yes"


def money(value: Any) -> str:
    try:
        return "${:,.0f}".format(float(value))
    except Exception:
        return "$0"


def clamp_nonnegative(value: Any) -> float:
    try:
        return max(float(value or 0), 0)
    except Exception:
        return 0.0


def slow_flip_functional_risks(notes: str) -> list[str]:
    text = str(notes or "").lower()
    risk_terms = {
        "low ceilings": ["low ceiling", "low ceilings", "ceiling height"],
        "no driveway": ["no driveway", "no parking", "shared driveway", "street parking only"],
        "termite damage": ["termite", "termites", "wood destroying", "wdi"],
        "weak rent comps": ["weak rent comp", "weak rent comps", "rent comps weak", "low rent comps", "rent support weak"],
    }
    return [label for label, terms in risk_terms.items() if any(term in text for term in terms)]


def calc_slow_flip(deal: OfferDealInput, assumptions: OfferAssumptions) -> dict[str, Any]:
    rent = clamp_nonnegative(deal.rent)
    asking = clamp_nonnegative(deal.asking_price)
    arv = clamp_nonnegative(deal.arv)
    repairs = clamp_nonnegative(deal.repairs)

    resale_to_slow_flipper = rent * assumptions.slow_flip_rent_multiple
    rent_formula_max_offer = max(
        resale_to_slow_flipper - assumptions.min_assignment_fee - assumptions.close_title_buffer,
        0,
    )
    value_repair_max_offer = (
        max((arv * 0.65) - repairs - assumptions.min_assignment_fee - assumptions.close_title_buffer, 0)
        if arv > 0
        else 0
    )
    functional_risks = slow_flip_functional_risks(deal.notes)
    risk_adjustment = 0.85 if functional_risks else 1.00
    adjusted_rent_formula_max_offer = rent_formula_max_offer * risk_adjustment
    adjusted_value_repair_max_offer = value_repair_max_offer * risk_adjustment if value_repair_max_offer > 0 else 0
    slow_flip_max_buy_price = clamp_nonnegative(assumptions.slow_flip_max_buy_price)
    above_slow_flip_max_buy_price = slow_flip_max_buy_price > 0 and asking > slow_flip_max_buy_price
    weak_rent = rent <= 0 or str(deal.rent_verification_needed) == "Yes" or str(deal.rent_confidence) in {
        "Weak",
        "Weak / seller stated only",
        "Missing",
        "Unknown",
        "",
    }

    normal_cap = clamp_nonnegative(assumptions.slow_flip_max_offer_cap)
    max_candidates = [adjusted_rent_formula_max_offer]
    if adjusted_value_repair_max_offer > 0:
        max_candidates.append(adjusted_value_repair_max_offer)
    if normal_cap > 0:
        max_candidates.append(normal_cap)
    if slow_flip_max_buy_price > 0:
        max_candidates.append(slow_flip_max_buy_price)
    max_contract_price = min(max_candidates)

    first_offer_gap = clamp_nonnegative(assumptions.slow_flip_first_offer_gap)
    first_offer = max(max_contract_price - first_offer_gap, 0)
    offer_to_send = min(first_offer, asking) if asking > 0 else first_offer
    estimated_fee_at_ask = resale_to_slow_flipper - asking - assumptions.close_title_buffer if asking else 0

    return {
        "exit": "Slow Flip",
        "resale_to_slow_flipper": resale_to_slow_flipper,
        "target_offer_low": offer_to_send,
        "target_offer_high": max_contract_price,
        "first_offer": first_offer,
        "offer_to_send": offer_to_send,
        "max_offer": max_contract_price,
        "rent_formula_max_offer_before_cap": rent_formula_max_offer,
        "risk_adjusted_rent_formula_max_offer": adjusted_rent_formula_max_offer,
        "value_repair_max_offer_before_cap": value_repair_max_offer,
        "risk_adjusted_value_repair_max_offer": adjusted_value_repair_max_offer,
        "normal_slow_flip_cap": normal_cap,
        "slow_flip_max_buy_price": slow_flip_max_buy_price,
        "slow_flip_max_source": assumptions.slow_flip_max_source,
        "above_slow_flip_max_buy_price": above_slow_flip_max_buy_price,
        "rent_source": deal.rent_source,
        "rent_confidence": deal.rent_confidence,
        "rent_verification_needed": "Yes" if weak_rent else "No",
        "slow_flip_rent_risk": (
            "Rent could not be verified. Slow Flip numbers are not reliable until rent comps are manually verified."
            if weak_rent
            else ""
        ),
        "functional_risks": functional_risks,
        "estimated_fee_at_ask": estimated_fee_at_ask,
        "spread": resale_to_slow_flipper - asking if asking else resale_to_slow_flipper,
    }


def calc_wholesale(deal: OfferDealInput, assumptions: OfferAssumptions) -> dict[str, Any]:
    arv = clamp_nonnegative(deal.arv)
    repairs = clamp_nonnegative(deal.repairs)
    asking = clamp_nonnegative(deal.asking_price)

    buyer_target = max((arv * assumptions.wholesale_buyer_percent_arv) - repairs, 0)
    max_contract_price = max(
        buyer_target - assumptions.min_assignment_fee - assumptions.close_title_buffer,
        0,
    )
    target_offer_high = max_contract_price * assumptions.target_offer_discount
    target_offer_low = target_offer_high * 0.90
    first_offer = target_offer_low
    offer_to_send = min(first_offer, asking) if asking > 0 else first_offer
    estimated_fee_at_ask = buyer_target - asking - assumptions.close_title_buffer if asking else 0

    return {
        "exit": "Wholesale",
        "buyer_target": buyer_target,
        "buyer_percent_arv": assumptions.wholesale_buyer_percent_arv,
        "buyer_percent_source": assumptions.wholesale_buyer_percent_source,
        "buyer_percent_range": assumptions.wholesale_buyer_percent_range,
        "buyer_percent_reason": assumptions.wholesale_buyer_percent_reason,
        "market_liquidity_tier": assumptions.market_liquidity_tier,
        "conservative_buyer_target": max((arv * max(assumptions.wholesale_buyer_percent_arv - 0.03, 0.50)) - repairs, 0),
        "aggressive_buyer_target": max((arv * min(assumptions.wholesale_buyer_percent_arv + 0.03, 0.78)) - repairs, 0),
        "market_buyer_percent_arv": assumptions.market_wholesale_buyer_percent,
        "needs_human_review": arv <= 0 or repairs <= 0 or assumptions.wholesale_buyer_percent_arv < 0.55,
        "target_offer_low": target_offer_low,
        "target_offer_high": target_offer_high,
        "first_offer": first_offer,
        "offer_to_send": offer_to_send,
        "max_offer": max_contract_price,
        "estimated_fee_at_ask": estimated_fee_at_ask,
        "spread": buyer_target - asking if asking else buyer_target,
    }


def choose_best_exit(wholesale: dict[str, Any], slow_flip: dict[str, Any], deal: OfferDealInput, assumptions: OfferAssumptions) -> str:
    notes = (deal.notes or "").lower()
    status = (deal.status or "").lower()
    livable = (deal.livable or "").lower()

    if "sold" in status:
        return "Pass"
    if any(word in notes for word in ["fire", "foundation", "condemned", "tear down", "teardown"]):
        return "Needs Human Review"
    if deal.exit_mode == "Slow Flip Only":
        if slow_flip.get("above_slow_flip_max_buy_price") or slow_flip.get("functional_risks") or slow_flip.get("rent_verification_needed") == "Yes":
            return "Needs Human Review"
        if livable == "no":
            return "Needs Human Review"
        return "Slow Flip" if slow_flip["estimated_fee_at_ask"] >= assumptions.exception_assignment_fee else "Needs Human Review"
    if deal.exit_mode == "Wholesale Only":
        return "Wholesale" if wholesale["estimated_fee_at_ask"] >= assumptions.exception_assignment_fee else "Needs Human Review"

    if (
        deal.rent >= 700
        and slow_flip["estimated_fee_at_ask"] >= assumptions.exception_assignment_fee
        and livable != "no"
        and not slow_flip.get("above_slow_flip_max_buy_price")
        and not slow_flip.get("functional_risks")
        and slow_flip.get("rent_verification_needed") != "Yes"
    ):
        return "Slow Flip"
    if wholesale["estimated_fee_at_ask"] >= assumptions.exception_assignment_fee:
        return "Wholesale"
    return "Needs Human Review"


def grade_deal(best: dict[str, Any], asking: float, assumptions: OfferAssumptions) -> str:
    fee = float(best.get("estimated_fee_at_ask", 0) or 0)
    max_offer = float(best.get("max_offer", 0) or 0)
    asking = clamp_nonnegative(asking)
    if asking > 0 and max_offer >= asking and fee >= 15000:
        return "A"
    if asking > 0 and max_offer >= asking and fee >= assumptions.min_assignment_fee:
        return "B"
    if asking > 0 and fee >= assumptions.exception_assignment_fee:
        return "C"
    if max_offer > 0:
        return "Review"
    return "Pass"


def analyze_deal(deal: OfferDealInput, assumptions: OfferAssumptions | None = None) -> dict[str, Any]:
    """Run the same core buy-box math used by the standalone War Room Offer Engine."""

    rules = assumptions or OfferAssumptions()
    wholesale = calc_wholesale(deal, rules)
    slow_flip = calc_slow_flip(deal, rules)

    if deal.exit_mode == "Slow Flip Only":
        best_exit = (
            "Slow Flip"
            if (
                deal.livable != "No"
                and not slow_flip.get("above_slow_flip_max_buy_price")
                and not slow_flip.get("functional_risks")
                and slow_flip.get("rent_verification_needed") != "Yes"
                and slow_flip["estimated_fee_at_ask"] >= rules.exception_assignment_fee
            )
            else "Needs Human Review"
        )
    elif deal.exit_mode == "Wholesale Only":
        best_exit = (
            "Needs Human Review"
            if wholesale.get("needs_human_review")
            else ("Wholesale" if wholesale["estimated_fee_at_ask"] >= rules.exception_assignment_fee else "Needs Human Review")
        )
    else:
        best_exit = choose_best_exit(wholesale, slow_flip, deal, rules)
        if best_exit == "Wholesale" and wholesale.get("needs_human_review"):
            best_exit = "Needs Human Review"

    if best_exit == "Wholesale":
        best = wholesale
    elif best_exit == "Slow Flip":
        best = slow_flip
    else:
        best = dict(slow_flip if deal.exit_mode == "Slow Flip Only" else wholesale)
        best["exit"] = best_exit

    return {
        "deal": asdict(deal),
        "assumptions": asdict(rules),
        "grade": grade_deal(best, deal.asking_price, rules) if best_exit != "Pass" else "Pass",
        "best_exit": best_exit,
        "best": best,
        "wholesale": wholesale,
        "slow_flip": slow_flip,
    }
