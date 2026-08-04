from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .marketing_claims import risky_condition_claim_errors
from .meta_marketplace_policy import (
    META_MARKETPLACE_POLICY_VERSION,
    REQUIRED_MARKETPLACE_DISCLOSURES,
    marketplace_disclaimer,
    meta_marketplace_policy_errors,
    meta_marketplace_policy_warnings,
)
from .models import OwnerFinanceProperty


@dataclass(frozen=True, slots=True)
class MarketplacePackage:
    title: str
    description: str


@dataclass(slots=True)
class MarketplaceCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    policy_version: str = META_MARKETPLACE_POLICY_VERSION

    @property
    def passed(self) -> bool:
        return not self.errors


def _money(value: Decimal | None) -> str:
    return "Not provided" if value is None else f"${value:,.0f}"


def _marketing_address(property_record: OwnerFinanceProperty) -> str:
    city_state = ", ".join(part for part in [property_record.city, property_record.state] if part)
    locality = f"{city_state} {property_record.zip_code}".strip()
    return ", ".join(part for part in [property_record.address, locality] if part)


def build_meta_safe_marketplace_package(
    property_record: OwnerFinanceProperty,
    tracked_dwelyx_link: str,
) -> MarketplacePackage:
    """Build conservative property copy designed for manual Marketplace publication."""
    address = _marketing_address(property_record)
    title = f"Owner-Finance Home — {address}" if address else "Owner-Finance Home Available"
    condition = property_record.condition_summary.strip() or "Condition details must be confirmed during review."
    repairs = property_record.repairs_needed.strip() or (
        "No repairs statement was provided. Buyers should verify the property's condition during review."
    )
    disclosures = property_record.public_disclosures.strip() or "Property information and terms must be verified."
    link_line = (
        "Create or log in to a Dwelyx buyer account to review available owner-finance homes: "
        f"{tracked_dwelyx_link}"
    )
    description = (
        f"{address}\n\n"
        f"{property_record.bedrooms or '—'} bed / {property_record.bathrooms or '—'} bath\n"
        f"Purchase price: {_money(property_record.total_price)}\n"
        f"Down payment: {_money(property_record.down_payment)}\n"
        f"Monthly payment: {_money(property_record.monthly_payment)}\n\n"
        f"Condition: {condition}\n\n"
        f"Known repairs or work needed: {repairs}\n\n"
        f"Disclosures: {disclosures}\n\n"
        f"{marketplace_disclaimer()}\n\n"
        f"{link_line}"
    )
    return MarketplacePackage(title=title, description=description)


def _money_is_present(text: str, value: Decimal) -> bool:
    formatted = f"${value:,.0f}"
    plain = f"${value:.0f}"
    return formatted in text or plain in text


def review_marketplace_copy(
    property_record: OwnerFinanceProperty,
    title: str,
    description: str,
    listings_used_this_month: int,
    monthly_limit: int = 5,
    tracked_dwelyx_link: str | None = None,
) -> MarketplaceCheck:
    result = MarketplaceCheck()
    combined = f"{title}\n{description}"

    if listings_used_this_month >= monthly_limit:
        result.errors.append("Internal posting-safety limit reached. Pause and review account health before another Marketplace listing.")

    result.errors.extend(meta_marketplace_policy_errors(combined))
    result.errors.extend(risky_condition_claim_errors(combined))
    result.warnings.extend(meta_marketplace_policy_warnings(combined))

    address = _marketing_address(property_record)
    if address and address.lower() not in combined.lower():
        result.errors.append("The complete property address must appear in the Marketplace package.")

    facts = {
        "total price": property_record.total_price,
        "down payment": property_record.down_payment,
        "monthly payment": property_record.monthly_payment,
    }
    for label, value in facts.items():
        if value is None:
            result.errors.append(f"Property is missing {label}; Marketplace package cannot be prepared.")
        elif not _money_is_present(description, value):
            result.errors.append(f"The exact {label} must appear in the Marketplace description.")

    if property_record.condition_summary and property_record.condition_summary.lower() not in description.lower():
        result.warnings.append("The saved condition summary is not quoted exactly. Confirm that no condition facts were changed.")
    if property_record.repairs_needed and property_record.repairs_needed.lower() not in description.lower():
        result.warnings.append("The saved repairs statement is not quoted exactly. Confirm that no known work was omitted.")

    if not property_record.public_disclosures:
        result.errors.append("Public disclosures are required before Marketplace publication.")
    elif property_record.public_disclosures.lower() not in description.lower():
        result.errors.append("The saved public disclosures must appear in the Marketplace description.")

    for disclosure in REQUIRED_MARKETPLACE_DISCLOSURES:
        if disclosure.lower() not in description.lower():
            result.errors.append(f'Required Marketplace disclosure is missing: "{disclosure}"')

    if tracked_dwelyx_link and tracked_dwelyx_link not in description:
        result.errors.append("The approved tracked Dwelyx buyer-account link is missing.")

    if len(title.strip()) < 15:
        result.warnings.append("Marketplace title may be too short to explain the opportunity clearly.")
    if len(description.strip()) < 250:
        result.warnings.append("Marketplace description may be too short to explain the property facts, condition, terms, and disclosures.")

    result.errors = sorted(set(result.errors))
    result.warnings = sorted(set(result.warnings))
    return result
