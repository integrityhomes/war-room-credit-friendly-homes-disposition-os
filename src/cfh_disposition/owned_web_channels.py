from __future__ import annotations

from dataclasses import dataclass

from .models import OwnerFinanceProperty


class OwnedWebPackageError(ValueError):
    """Raised when an owned-web package cannot be built safely."""


@dataclass(frozen=True, slots=True)
class OwnedWebPackage:
    channel_key: str
    channel_name: str
    title: str
    meta_description: str
    headline: str
    body: str
    call_to_action: str
    tracked_link: str
    keyword_targets: tuple[str, ...]


def _validate(property_: OwnerFinanceProperty, *, channel_key: str, tracked_link: str) -> None:
    if channel_key not in {"property_page", "blog", "market_seo"}:
        raise OwnedWebPackageError(f"Unsupported owned-web channel: {channel_key}")
    if not property_.address:
        raise OwnedWebPackageError("A street address is required.")
    if not property_.city or not property_.state:
        raise OwnedWebPackageError("City and state are required.")
    if not tracked_link.strip():
        raise OwnedWebPackageError("A tracked Dwelyx link is required.")


def _fact_line(property_: OwnerFinanceProperty) -> str:
    facts: list[str] = []
    if property_.bedrooms is not None:
        facts.append(f"{property_.bedrooms} bedrooms")
    if property_.bathrooms is not None:
        facts.append(f"{property_.bathrooms:g} bathrooms")
    if property_.monthly_payment is not None:
        facts.append(f"monthly payment from ${property_.monthly_payment:,.0f}")
    if property_.down_payment is not None:
        facts.append(f"down payment from ${property_.down_payment:,.0f}")
    return ", ".join(facts)


def build_owned_web_package(
    property_: OwnerFinanceProperty,
    *,
    channel_key: str,
    channel_name: str,
    tracked_link: str,
) -> OwnedWebPackage:
    """Build fact-safe copy for CFH-owned pages and SEO content."""
    _validate(property_, channel_key=channel_key, tracked_link=tracked_link)

    address = property_.display_address
    location = f"{property_.city}, {property_.state}"
    facts = _fact_line(property_)
    fact_sentence = f" Current verified details include {facts}." if facts else ""

    if channel_key == "property_page":
        title = f"Owner-Finance Home at {address} | Credit Friendly Homes"
        headline = f"Explore {address}"
        meta_description = (
            f"View current owner-finance details for {address} in {location}, plus next steps in Dwelyx."
        )
        body = (
            f"Looking for a home in {location}? Review the current information for {address}."
            f"{fact_sentence} Property availability and terms can change, so use the Dwelyx link for the latest details, "
            "showing requests, and next steps. Approval is not guaranteed."
        )
        keywords = (f"owner financing {location}", f"owner finance home {property_.city}", address)
    elif channel_key == "blog":
        title = f"How to Explore Owner-Finance Homes in {location} | Credit Friendly Homes"
        headline = f"Looking for owner financing in {location}?"
        meta_description = (
            f"Learn how buyers can review owner-finance opportunities in {location} and see a current example property."
        )
        body = (
            f"Buyers searching for alternatives to traditional financing often want a clear way to compare current homes, "
            f"terms, and next steps. One current example in {location} is {address}.{fact_sentence} "
            "Use Dwelyx to review current property details and availability. This educational content does not guarantee "
            "approval or that any specific property will remain available."
        )
        keywords = (f"owner financing {location}", f"credit friendly homes {location}", f"homes for sale {property_.city}")
    else:
        title = f"Owner-Finance Homes in {location} | Credit Friendly Homes"
        headline = f"Owner-finance homes in {location}"
        meta_description = (
            f"Explore current owner-finance opportunities in {location} and review available homes through Dwelyx."
        )
        body = (
            f"Credit Friendly Homes helps buyers discover current owner-finance opportunities in {location}. "
            f"A current property example is {address}.{fact_sentence} Inventory and terms change over time. "
            "Use Dwelyx for the latest property details, availability, and next steps. Approval is not guaranteed."
        )
        keywords = (f"owner finance homes {location}", f"owner financing {property_.city}", f"homes {property_.city} {property_.state}")

    return OwnedWebPackage(
        channel_key=channel_key,
        channel_name=channel_name,
        title=title,
        meta_description=meta_description,
        headline=headline,
        body=body,
        call_to_action="View current details in Dwelyx",
        tracked_link=tracked_link,
        keyword_targets=keywords,
    )
