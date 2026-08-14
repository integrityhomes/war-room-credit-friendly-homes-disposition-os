from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import OwnerFinanceProperty


class OutreachPackageError(ValueError):
    """Raised when an outreach package cannot be built safely."""


@dataclass(frozen=True, slots=True)
class OutreachPackage:
    channel_key: str
    channel_name: str
    subject: str
    message_variants: tuple[str, ...]
    tracked_link: str
    compliance_notes: tuple[str, ...]


def _money(value: Decimal | None) -> str:
    return f"${value:,.0f}" if value is not None else ""


def _validate(property_: OwnerFinanceProperty, channel_key: str, tracked_link: str) -> None:
    if channel_key not in {"email", "sms", "reactivation"}:
        raise OutreachPackageError(f"Unsupported outreach channel: {channel_key}")
    if not property_.address.strip():
        raise OutreachPackageError("Property address is required before creating outreach copy.")
    if property_.monthly_payment is None and property_.down_payment is None:
        raise OutreachPackageError("Add a monthly payment or down payment before creating outreach copy.")
    if not tracked_link.strip():
        raise OutreachPackageError("A tracked Dwelyx link is required.")


def build_outreach_package(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    channel_name: str,
    tracked_link: str,
) -> OutreachPackage:
    """Build fact-safe email, SMS, or reactivation copy for a saved property."""
    _validate(property_, channel_key, tracked_link)

    address = property_.display_address
    payment = _money(property_.monthly_payment)
    down = _money(property_.down_payment)
    terms: list[str] = []
    if payment:
        terms.append(f"{payment}/mo")
    if down:
        terms.append(f"{down} down")
    term_line = " • ".join(terms)

    if channel_key == "email":
        subject = f"New owner-finance home: {address}"
        variants = (
            f"A home that may fit what you're looking for is now available at {address}. {term_line}. Review the current details and next steps here: {tracked_link}",
            f"Take a look at {address}. Current owner-finance terms include {term_line}. See the property details in Dwelyx: {tracked_link}",
            f"New Credit Friendly Homes opportunity: {address}. {term_line}. View current availability and next steps: {tracked_link}",
        )
        notes = (
            "Send only to buyers with saved email consent.",
            "Honor unsubscribe and do-not-contact status before sending.",
            "Do not promise approval or change verified property terms.",
        )
    elif channel_key == "sms":
        subject = "Matched Buyer SMS"
        variants = (
            f"Credit Friendly Homes: {address} may fit what you're looking for. {term_line}. Details: {tracked_link}",
            f"New home alert: {address}. {term_line}. See current details: {tracked_link}",
            f"Owner-finance home available at {address}. {term_line}. View it here: {tracked_link}",
        )
        notes = (
            "Send only to buyers with saved SMS consent.",
            "Honor STOP/do-not-contact status before sending.",
            "Do not promise approval or use misleading urgency.",
        )
    else:
        subject = f"Still looking for a home? {address}"
        variants = (
            f"Still looking for a home? We have another option at {address}. {term_line}. See the current details here: {tracked_link}",
            f"Checking back in because a new owner-finance home is available at {address}. {term_line}. Details: {tracked_link}",
            f"If you're still looking, {address} may be worth a look. {term_line}. Review current details: {tracked_link}",
        )
        notes = (
            "Re-engage only buyers whose saved consent still permits contact.",
            "Exclude do-not-contact buyers and expired/withdrawn consent.",
            "Do not imply the buyer is approved or guaranteed to qualify.",
        )

    return OutreachPackage(
        channel_key=channel_key,
        channel_name=channel_name,
        subject=subject,
        message_variants=variants,
        tracked_link=tracked_link,
        compliance_notes=notes,
    )
