from __future__ import annotations

from dataclasses import dataclass

from .models import OwnerFinanceProperty


class ClassifiedsPackageError(ValueError):
    """Raised when required property facts are missing from a classifieds package."""


@dataclass(frozen=True, slots=True)
class ClassifiedsPackage:
    channel_key: str
    channel_name: str
    headline: str
    body_variants: tuple[str, ...]
    short_body: str
    fact_summary: tuple[str, ...]
    posting_checklist: tuple[str, ...]
    call_to_action: str
    tracked_link: str


def _money(value) -> str:
    return f"${value:,.0f}" if value is not None else ""


def _validate(property_: OwnerFinanceProperty, tracked_link: str) -> None:
    if not property_.address:
        raise ClassifiedsPackageError("Property street address is required.")
    if not property_.city or not property_.state:
        raise ClassifiedsPackageError("Property city and state are required.")
    if property_.monthly_payment is None and property_.total_price is None:
        raise ClassifiedsPackageError("Add at least a monthly payment or total price.")
    if not tracked_link.strip():
        raise ClassifiedsPackageError("A tracked Dwelyx link is required.")


def _facts(property_: OwnerFinanceProperty) -> tuple[str, ...]:
    facts: list[str] = []
    if property_.bedrooms is not None:
        facts.append(f"{property_.bedrooms} bedroom" + ("" if property_.bedrooms == 1 else "s"))
    if property_.bathrooms is not None:
        facts.append(f"{property_.bathrooms:g} bathroom" + ("" if property_.bathrooms == 1 else "s"))
    if property_.monthly_payment is not None:
        facts.append(f"Monthly payment: {_money(property_.monthly_payment)}")
    if property_.down_payment is not None:
        facts.append(f"Down payment: {_money(property_.down_payment)}")
    if property_.total_price is not None:
        facts.append(f"Price: {_money(property_.total_price)}")
    if property_.condition_summary:
        facts.append(f"Condition: {property_.condition_summary}")
    if property_.repairs_needed:
        facts.append(f"Repairs / work noted: {property_.repairs_needed}")
    return tuple(facts)


def build_classifieds_package(
    property_: OwnerFinanceProperty,
    *,
    tracked_link: str,
    channel_name: str = "Craigslist & Local Classifieds",
) -> ClassifiedsPackage:
    """Build fact-only copy for Craigslist and other local classified placements."""
    _validate(property_, tracked_link)
    address = property_.display_address
    location = f"{property_.city}, {property_.state}"
    facts = _facts(property_)
    fact_text = "\n".join(f"• {fact}" for fact in facts)

    headline = f"Owner-Finance Home Available in {location}"
    intro = (
        f"Owner-finance home available at {address}. "
        "Review the current property details below and use the Dwelyx link for the latest availability and next steps."
    )
    condition_note = (
        "The home is being presented in its current condition. Review the photos, disclosures, and property details before deciding whether it is a fit."
    )
    cta = "View current details and next steps in Dwelyx"

    body_variants = (
        f"{headline}\n\n{intro}\n\n{fact_text}\n\n{condition_note}\n\n{cta}:\n{tracked_link}",
        f"Looking for an owner-finance home in {location}?\n\nAddress: {address}\n\n{fact_text}\n\n{condition_note}\n\nSee the current property details here:\n{tracked_link}",
        f"Property opportunity: {address}\n\n{fact_text}\n\nUse the tracked Dwelyx page to review current availability, property details, and next steps:\n{tracked_link}",
    )

    short_body = (
        f"Owner-finance home available at {address}. "
        + "; ".join(facts[:4])
        + f". Current details: {tracked_link}"
    )

    posting_checklist = (
        "Confirm the property is still available before posting or refreshing the classified.",
        "Use current property photos without digitally changing the home's physical condition.",
        "Keep the exact tracked Dwelyx link with this classified so results remain attributable.",
        "Review the final copy for accurate property terms and disclosures before publication.",
        "Do not add approval guarantees, protected-class language, or unsupported property claims.",
    )

    return ClassifiedsPackage(
        channel_key="classifieds",
        channel_name=channel_name,
        headline=headline,
        body_variants=body_variants,
        short_body=short_body,
        fact_summary=facts,
        posting_checklist=posting_checklist,
        call_to_action=cta,
        tracked_link=tracked_link,
    )
