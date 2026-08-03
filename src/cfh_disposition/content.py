from __future__ import annotations

from dataclasses import dataclass

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
    headline = f"Owner-Financed Home Available — {address}" if address else "Owner-Financed Home Available"
    payment = f"${property_record.monthly_payment:,.0f}" if property_record.monthly_payment is not None else "See terms"
    down = f"${property_record.down_payment:,.0f}" if property_record.down_payment is not None else "See terms"
    facts = f"{property_record.bedrooms or '—'} bed / {property_record.bathrooms or '—'} bath"
    short = f"{address}: {facts} owner-finance opportunity. Approx. {payment}/month with {down} down. {property_record.condition_summary}"
    marketplace = (
        f"{headline}\n\n{short}\n\nKnown repairs: {property_record.repairs_needed or 'Confirm during review.'}\n\n"
        f"{property_record.public_disclosures}"
    )
    return CampaignDraft(
        headline=headline,
        short_description=short,
        marketplace_description=marketplace,
        email_subject=f"Owner-financed home at {address}",
        sms_message=f"{address}: owner-financed home at about {payment}/mo and {down} down. Reply for details.",
    )
