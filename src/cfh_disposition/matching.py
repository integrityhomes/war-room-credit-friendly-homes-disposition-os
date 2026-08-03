from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import BuyerProfile, OwnerFinanceProperty


@dataclass(frozen=True, slots=True)
class BuyerMatch:
    buyer: BuyerProfile
    score: int
    reasons: tuple[str, ...]
    disqualifiers: tuple[str, ...]

    @property
    def is_eligible(self) -> bool:
        return not self.disqualifiers and self.score >= 40


def match_buyer_to_property(buyer: BuyerProfile, property_record: OwnerFinanceProperty) -> BuyerMatch:
    score = 0
    reasons: list[str] = []
    disqualifiers: list[str] = []

    if buyer.do_not_contact:
        disqualifiers.append("Buyer is marked Do Not Contact.")

    if property_record.state and property_record.state in buyer.preferred_states:
        score += 25
        reasons.append("Preferred state match.")
    if property_record.city and property_record.city.lower() in {city.lower() for city in buyer.preferred_cities}:
        score += 25
        reasons.append("Preferred city match.")

    if buyer.minimum_bedrooms is not None and property_record.bedrooms is not None:
        if property_record.bedrooms >= buyer.minimum_bedrooms:
            score += 15
            reasons.append("Bedroom requirement met.")
        else:
            disqualifiers.append("Property has fewer bedrooms than requested.")

    if buyer.maximum_monthly_payment is not None and property_record.monthly_payment is not None:
        if property_record.monthly_payment <= buyer.maximum_monthly_payment:
            score += 20
            reasons.append("Monthly payment is within range.")
        else:
            disqualifiers.append("Monthly payment exceeds buyer range.")

    if buyer.available_down_payment is not None and property_record.down_payment is not None:
        if buyer.available_down_payment >= property_record.down_payment:
            score += 15
            reasons.append("Available down payment appears sufficient.")
        elif buyer.available_down_payment < property_record.down_payment * Decimal("0.75"):
            disqualifiers.append("Available down payment is materially below the stated requirement.")

    return BuyerMatch(buyer=buyer, score=min(score, 100), reasons=tuple(reasons), disqualifiers=tuple(disqualifiers))
