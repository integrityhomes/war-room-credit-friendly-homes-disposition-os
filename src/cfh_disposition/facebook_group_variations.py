from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .models import OwnerFinanceProperty

VARIATION_COUNT = 8
PROHIBITED_GROUP_PHRASES = (
    "move-in ready",
    "move in ready",
    "move-in-ready",
    "guaranteed approval",
    "everyone approved",
    "no credit check",
    "safe neighborhood",
    "crime-free",
    "perfect for families",
)


@dataclass(frozen=True, slots=True)
class FacebookGroupVariation:
    index: int
    label: str
    copy: str


HEADLINES = (
    "Owner-Finance Home Available",
    "Owner-Finance Property Details",
    "Home Available With Owner-Finance Terms",
    "Review This Owner-Finance Home",
    "Owner-Finance Opportunity",
    "Available Home With Seller-Finance Terms",
    "Property Available With Owner Financing",
    "Owner-Finance Home Information",
)

CTA_LINES = (
    "Create or log in to your Dwelyx buyer account to review available owner-finance homes:",
    "Review available owner-finance homes through your Dwelyx buyer account:",
    "Create or access your Dwelyx buyer account to review available homes:",
    "Buyer details and available owner-finance homes are available through Dwelyx:",
    "Use Dwelyx to review available owner-finance homes and buyer next steps:",
    "Open your Dwelyx buyer account to review available owner-finance homes:",
    "Review current owner-finance availability through Dwelyx:",
    "Create or log in to Dwelyx to review available owner-finance homes:",
)


def _money(value: Decimal | None) -> str:
    return "Not provided" if value is None else f"${value:,.0f}"


def _bed_bath_line(property_record: OwnerFinanceProperty) -> str:
    bedrooms = property_record.bedrooms if property_record.bedrooms is not None else "—"
    bathrooms = property_record.bathrooms if property_record.bathrooms is not None else "—"
    square_feet = (
        f" | {property_record.square_feet:,} sq ft"
        if property_record.square_feet is not None
        else ""
    )
    return f"{bedrooms} bed / {bathrooms} bath{square_feet}"


def variation_index(
    property_id: UUID | str,
    group_id: str,
    *,
    prior_post_count: int = 0,
) -> int:
    seed = f"{property_id}|{group_id}".encode("utf-8")
    base = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big")
    return (base + max(prior_post_count, 0)) % VARIATION_COUNT


def _fact_sections(property_record: OwnerFinanceProperty) -> dict[str, str]:
    address = property_record.display_address or "Address available in the property record"
    condition = (
        property_record.condition_summary
        or "Buyers should independently inspect and verify the property's condition."
    )
    repairs = (
        property_record.repairs_needed
        or "No repair statement was provided. Buyers should verify condition and needed work."
    )
    disclosures = (
        property_record.public_disclosures
        or "Property information, condition, terms, and availability must be verified."
    )
    return {
        "address": address,
        "facts": _bed_bath_line(property_record),
        "terms": (
            f"Down payment: {_money(property_record.down_payment)}\n"
            f"Monthly owner-finance payment: {_money(property_record.monthly_payment)}\n"
            "The monthly payment shown is not rent."
        ),
        "condition": f"Condition: {condition}",
        "repairs": f"Known repairs or work needed: {repairs}",
        "disclosures": f"Disclosures: {disclosures}",
        "compliance": (
            "Approval, terms, and availability are subject to review and verification.\n"
            "No payment is requested through Facebook.\n"
            "Equal Housing Opportunity."
        ),
    }


def _ordered_sections(index: int, sections: dict[str, str]) -> list[str]:
    orders = (
        ("address", "facts", "terms", "condition", "repairs", "disclosures", "compliance"),
        ("address", "terms", "facts", "condition", "repairs", "disclosures", "compliance"),
        ("address", "facts", "condition", "repairs", "terms", "disclosures", "compliance"),
        ("address", "condition", "facts", "terms", "repairs", "disclosures", "compliance"),
        ("address", "facts", "repairs", "condition", "terms", "disclosures", "compliance"),
        ("address", "terms", "condition", "facts", "repairs", "disclosures", "compliance"),
        ("address", "facts", "disclosures", "terms", "condition", "repairs", "compliance"),
        ("address", "condition", "repairs", "facts", "terms", "disclosures", "compliance"),
    )
    return [sections[key] for key in orders[index % VARIATION_COUNT]]


def build_facebook_group_variation(
    property_record: OwnerFinanceProperty,
    tracked_link: str,
    *,
    group_id: str,
    prior_post_count: int = 0,
) -> FacebookGroupVariation:
    index = variation_index(
        property_record.property_id,
        group_id,
        prior_post_count=prior_post_count,
    )
    sections = _fact_sections(property_record)
    body = "\n\n".join(_ordered_sections(index, sections))
    copy = f"{HEADLINES[index]}\n\n{body}\n\n{CTA_LINES[index]}\n{tracked_link}"
    return FacebookGroupVariation(
        index=index,
        label=f"Variation {index + 1} of {VARIATION_COUNT}",
        copy=copy,
    )


def validate_facebook_group_variation(
    variation: FacebookGroupVariation,
    property_record: OwnerFinanceProperty,
    tracked_link: str,
) -> list[str]:
    errors: list[str] = []
    lowered = variation.copy.casefold()
    address = property_record.display_address
    if address and address.casefold() not in lowered:
        errors.append("The complete property address is missing.")
    for label, value in (
        ("down payment", property_record.down_payment),
        ("monthly payment", property_record.monthly_payment),
    ):
        if value is None:
            errors.append(f"The property record is missing {label}.")
        elif _money(value) not in variation.copy:
            errors.append(f"The exact {label} is missing.")
    if property_record.total_price is not None and _money(property_record.total_price) in variation.copy:
        errors.append("The total purchase price should not appear in the public Facebook Group copy.")
    if variation.copy.count(tracked_link) != 1:
        errors.append("The tracked Dwelyx link must appear exactly once.")
    if "not rent" not in lowered:
        errors.append('The copy must state that the monthly payment is "not rent."')
    for phrase in PROHIBITED_GROUP_PHRASES:
        if phrase in lowered:
            errors.append(f"Prohibited Facebook Group phrase detected: {phrase}")
    return sorted(set(errors))
