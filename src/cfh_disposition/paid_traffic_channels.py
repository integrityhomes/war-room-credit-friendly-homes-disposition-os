from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import OwnerFinanceProperty


class PaidTrafficPackageError(ValueError):
    """Raised when a paid-traffic package cannot be built safely."""


@dataclass(frozen=True, slots=True)
class PaidTrafficPackage:
    channel_key: str
    channel_name: str
    headline_options: tuple[str, ...]
    primary_text_options: tuple[str, ...]
    description: str
    call_to_action: str
    tracked_link: str
    campaign_name: str
    daily_budget: Decimal
    monthly_budget_cap: Decimal
    approval_notes: tuple[str, ...]


def _money(value: Decimal | None) -> str:
    return f"${value:,.0f}" if value is not None else ""


def _location(property_: OwnerFinanceProperty) -> str:
    if property_.city and property_.state:
        return f"{property_.city}, {property_.state}"
    return property_.city or property_.state or "your area"


def _validate(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    tracked_link: str,
    campaign_name: str,
    daily_budget: Decimal,
    monthly_budget_cap: Decimal,
) -> None:
    if channel_key not in {"meta_ads", "google_ads"}:
        raise PaidTrafficPackageError(f"Unsupported paid channel: {channel_key}")
    if not property_.address.strip():
        raise PaidTrafficPackageError("Property address is required before creating paid ads.")
    if property_.monthly_payment is None and property_.down_payment is None:
        raise PaidTrafficPackageError("Add a monthly payment or down payment before creating paid ads.")
    if not tracked_link.strip():
        raise PaidTrafficPackageError("A tracked Dwelyx link is required.")
    if not campaign_name.strip():
        raise PaidTrafficPackageError("Campaign name is required.")
    if daily_budget <= 0 or monthly_budget_cap <= 0:
        raise PaidTrafficPackageError("Budgets must be greater than zero.")
    if daily_budget * Decimal("31") > monthly_budget_cap * Decimal("1.25"):
        raise PaidTrafficPackageError("Daily budget is materially above the monthly budget cap.")


def build_paid_traffic_package(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    channel_name: str,
    tracked_link: str,
    campaign_name: str,
    daily_budget: Decimal,
    monthly_budget_cap: Decimal,
) -> PaidTrafficPackage:
    """Build a fact-safe, approval-controlled paid acquisition package."""
    _validate(
        property_,
        channel_key=channel_key,
        tracked_link=tracked_link,
        campaign_name=campaign_name,
        daily_budget=daily_budget,
        monthly_budget_cap=monthly_budget_cap,
    )

    location = _location(property_)
    address = property_.display_address
    payment = _money(property_.monthly_payment)
    down = _money(property_.down_payment)

    facts: list[str] = []
    if property_.bedrooms is not None:
        facts.append(f"{property_.bedrooms} bed")
    if property_.bathrooms is not None:
        facts.append(f"{property_.bathrooms:g} bath")
    if payment:
        facts.append(f"{payment}/mo")
    if down:
        facts.append(f"{down} down")
    fact_line = " • ".join(facts)

    if channel_key == "meta_ads":
        headlines = (
            f"Owner-Finance Home in {location}",
            f"See {address}",
            f"Explore Owner Financing in {location}",
        )
        primary = (
            f"Looking for a home in {location}? Take a look at {address}. {fact_line}. View current details and next steps in Dwelyx.",
            f"New owner-finance opportunity: {address}. {fact_line}. See the current property details in Dwelyx.",
            f"Explore this available home in {location}. {fact_line}. Use the link to review current details and next steps.",
        )
        description = "Current property details and next steps in Dwelyx. Approval is not guaranteed."
        notes = (
            "Treat as a housing-related ad and complete the platform's current housing-category setup during final ad creation.",
            "Do not use protected-class targeting, discriminatory copy, approval guarantees, or no-credit-check claims.",
            "Manager must approve targeting, budget, creative, and final publication before spend begins.",
        )
    else:
        headlines = (
            f"Owner Finance Home {location}",
            f"Owner Financing in {location}",
            f"View Home at {address}",
        )
        primary = (
            f"Owner-finance home available in {location}. {fact_line}. View current details in Dwelyx.",
            f"Explore {address}. {fact_line}. Check current property details and next steps.",
            f"Looking for owner financing in {location}? See {address} and review the current details in Dwelyx.",
        )
        description = "Property-specific search campaign with tracked Dwelyx destination. Approval is not guaranteed."
        notes = (
            "Use only location/property-intent keywords; do not create discriminatory audience exclusions or protected-class language.",
            "Review current Google Ads housing/financial-services requirements during final campaign setup.",
            "Manager must approve keywords, negatives, budget, creative, and final publication before spend begins.",
        )

    return PaidTrafficPackage(
        channel_key=channel_key,
        channel_name=channel_name,
        headline_options=headlines,
        primary_text_options=primary,
        description=description,
        call_to_action="View current details in Dwelyx",
        tracked_link=tracked_link,
        campaign_name=campaign_name,
        daily_budget=daily_budget,
        monthly_budget_cap=monthly_budget_cap,
        approval_notes=notes,
    )
