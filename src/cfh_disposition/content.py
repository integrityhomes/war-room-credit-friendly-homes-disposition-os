from __future__ import annotations

from dataclasses import dataclass

from .meta_marketplace_policy import marketplace_disclaimer
from .models import OwnerFinanceProperty


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    headline: str
    short_description: str
    marketplace_description: str
    email_subject: str
    sms_message: str


def _marketing_address(property_record: OwnerFinanceProperty) -> str:
    city_state = ", ".join(part for part in [property_record.city, property_record.state] if part)
    locality = f"{city_state} {property_record.zip_code}".strip()
    return ", ".join(part for part in [property_record.address, locality] if part)


def build_deterministic_campaign_draft(property_record: OwnerFinanceProperty) -> CampaignDraft:
    """Safe non-AI fallback used until the OpenAI adapter is connected."""
    address = _marketing_address(property_record)
    headline = f"Owner-Finance Home — {address}" if address else "Owner-Finance Home Available"
    price = f"${property_record.total_price:,.0f}" if property_record.total_price is not None else "See terms"
    payment = f"${property_record.monthly_payment:,.0f}" if property_record.monthly_payment is not None else "See terms"
    down = f"${property_record.down_payment:,.0f}" if property_record.down_payment is not None else "See terms"
    facts = f"{property_record.bedrooms or '—'} bed / {property_record.bathrooms or '—'} bath"
    condition = property_record.condition_summary or "Condition details must be confirmed during review."
    repairs = property_record.repairs_needed or (
        "No repairs statement was provided. Buyers should verify the property's condition during review."
    )
    disclosures = property_record.public_disclosures or "Property information and terms must be verified."
    short = (
        f"{address}: {facts} owner-finance opportunity. Purchase price {price}, approximately {payment}/month, "
        f"with {down} down. {condition}"
    )
    marketplace = (
        f"{headline}\n\n"
        f"{facts}\n"
        f"Purchase price: {price}\n"
        f"Down payment: {down}\n"
        f"Monthly payment: {payment}\n\n"
        f"Condition: {condition}\n\n"
        f"Known repairs or work needed: {repairs}\n\n"
        f"Disclosures: {disclosures}\n\n"
        f"{marketplace_disclaimer()}"
    )
    return CampaignDraft(
        headline=headline,
        short_description=short,
        marketplace_description=marketplace,
        email_subject=f"Owner-finance home at {address}",
        sms_message=(
            f"{address}: owner-finance home at approximately {payment}/month with {down} down. "
            "Approval, terms, and availability are subject to review and verification."
        ),
    )
