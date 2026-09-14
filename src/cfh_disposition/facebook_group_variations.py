from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .models import OwnerFinanceProperty

VARIATION_COUNT = 8
URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", flags=re.IGNORECASE)
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
    "Send us a Facebook message for complete purchase terms, property questions, and next steps.",
    "Message us through Facebook for complete purchase terms, property questions, and next steps.",
    "Use Facebook messaging if you want complete purchase terms or have property questions.",
    "For complete purchase terms and next steps, send us a Facebook message.",
    "Questions about the property or purchase terms? Send us a Facebook message.",
    "Send a Facebook message to review complete purchase terms and next steps.",
    "Use Facebook messaging for property questions, complete purchase terms, and next steps.",
    "Message us on Facebook for complete purchase terms and property questions.",
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
    seed = f"{property_id}|{group_id}".encode()
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
    """Build Facebook Group copy while keeping the public post on-platform.

    tracked_link remains in the function signature because assignments use it internally for
    attribution, but it is deliberately not inserted into the Facebook Group post.
    """
    _ = tracked_link
    index = variation_index(
        property_record.property_id,
        group_id,
        prior_post_count=prior_post_count,
    )
    sections = _fact_sections(property_record)
    body = "\n\n".join(_ordered_sections(index, sections))
    copy = f"{HEADLINES[index]}\n\n{body}\n\n{CTA_LINES[index]}"
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
    if tracked_link and tracked_link in variation.copy:
        errors.append("Do not place the tracked Dwelyx link in public Facebook Group copy.")
    if URL_PATTERN.search(variation.copy):
        errors.append("Remove website links from public Facebook Group copy and keep the first response inside Facebook.")
    if "dwelyx" in lowered:
        errors.append("Do not direct Facebook Group readers to Dwelyx in the public post.")
    if "facebook" not in lowered or "message" not in lowered:
        errors.append("Facebook Group copy must direct the first buyer response through Facebook messaging.")
    if "not rent" not in lowered:
        errors.append('The copy must state that the monthly payment is "not rent."')
    for phrase in PROHIBITED_GROUP_PHRASES:
        if phrase in lowered:
            errors.append(f"Prohibited Facebook Group phrase detected: {phrase}")
    return sorted(set(errors))
