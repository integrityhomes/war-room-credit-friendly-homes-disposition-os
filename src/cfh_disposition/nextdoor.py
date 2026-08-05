from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import OwnerFinanceProperty

NEXTDOOR_ADVERTISER_NAME_LIMIT = 70
NEXTDOOR_HEADLINE_LIMIT = 70
NEXTDOOR_BODY_LIMIT = 1700
NEXTDOOR_CTA_LIMIT = 45
NEXTDOOR_IMAGE_SPECS = "1200 × 628 px rectangle or 1200 × 1200 px square; JPEG or PNG."

PROHIBITED_NEXTDOOR_PHRASES = (
    "guaranteed approval",
    "everyone approved",
    "no credit check",
    "instant approval",
    "bad credit guaranteed",
    "perfect for families",
    "families only",
    "safe neighborhood",
    "crime-free",
    "best schools",
    "good schools",
    "preferred buyer",
    "financial distress",
    "desperate buyers",
    "move-in ready",
    "move in ready",
)


class NextdoorPackageError(RuntimeError):
    """Raised when a Nextdoor package fails the fact or policy guard."""


@dataclass(frozen=True, slots=True)
class NextdoorPackage:
    business_post_title: str
    business_post_body: str
    paid_ad_headline: str
    paid_ad_body: str
    paid_ad_cta: str
    tracked_link: str
    publication_instructions: tuple[str, ...]


def _money(value: Decimal | None) -> str:
    return "Not provided" if value is None else f"${value:,.0f}"


def _trim(value: str, limit: int) -> str:
    cleaned = " ".join(value.split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[: max(1, limit - 1)].rstrip(" ,.;:-")
    return f"{shortened}…"


def validate_nextdoor_copy(
    text: str,
    property_record: OwnerFinanceProperty,
    tracked_link: str,
) -> list[str]:
    errors: list[str] = []
    lowered = text.casefold()
    if property_record.display_address.casefold() not in lowered:
        errors.append("The exact property address is missing.")
    if property_record.down_payment is None or _money(property_record.down_payment) not in text:
        errors.append("The exact down payment is missing.")
    if property_record.monthly_payment is None or _money(property_record.monthly_payment) not in text:
        errors.append("The exact monthly owner-finance payment is missing.")
    if "not rent" not in lowered:
        errors.append('The copy must state that the monthly payment is "not rent."')
    if "subject to review and verification" not in lowered:
        errors.append("The approval, terms, condition, and availability disclaimer is missing.")
    if "equal housing opportunity" not in lowered:
        errors.append("Equal Housing Opportunity language is missing.")
    if text.count(tracked_link) != 1:
        errors.append("The tracked Dwelyx link must appear exactly once.")
    if property_record.total_price is not None and _money(property_record.total_price) in text:
        errors.append("The public Nextdoor package must not show the total purchase price.")
    for phrase in PROHIBITED_NEXTDOOR_PHRASES:
        if phrase in lowered:
            errors.append(f"Prohibited Nextdoor housing phrase detected: {phrase}")
    return sorted(set(errors))


def build_nextdoor_package(
    property_record: OwnerFinanceProperty,
    tracked_link: str,
) -> NextdoorPackage:
    if not tracked_link.strip():
        raise NextdoorPackageError("A tracked Dwelyx link is required for Nextdoor.")
    if property_record.down_payment is None or property_record.monthly_payment is None:
        raise NextdoorPackageError(
            "The property needs an exact down payment and monthly payment before creating Nextdoor copy."
        )

    address = property_record.display_address
    down = _money(property_record.down_payment)
    monthly = _money(property_record.monthly_payment)
    condition = property_record.condition_summary or (
        "Buyers should independently inspect and verify the property's condition."
    )
    repairs = property_record.repairs_needed or (
        "No repair statement was provided; buyers should verify any work needed."
    )
    disclosures = property_record.public_disclosures or (
        "Property information, condition, terms, and availability must be verified."
    )
    disclaimer = (
        "Approval, terms, property condition, and availability are subject to review and verification. "
        "Equal Housing Opportunity."
    )

    title = _trim(f"Owner-finance home information: {address}", NEXTDOOR_HEADLINE_LIMIT)
    body = (
        f"Owner-finance home information for {address}.\n\n"
        f"Down payment currently shown: {down}\n"
        f"Monthly owner-finance payment currently shown: {monthly}\n"
        "The monthly payment shown is not rent.\n\n"
        f"Condition: {condition}\n\n"
        f"Known repairs or work needed: {repairs}\n\n"
        f"Disclosures: {disclosures}\n\n"
        f"Create or log in to a Dwelyx buyer account to review current details and availability: {tracked_link}\n\n"
        f"{disclaimer}"
    )
    if len(body) > NEXTDOOR_BODY_LIMIT:
        raise NextdoorPackageError(
            "The saved property condition, repair, or disclosure text is too long for a Nextdoor ad. Shorten those factual fields without removing required disclosures."
        )

    paid_headline = _trim(f"Owner-finance home at {address}", NEXTDOOR_HEADLINE_LIMIT)
    paid_body = body
    paid_cta = "Review current details"

    for label, value in (
        ("Business Post", body),
        ("Paid Housing Ad", paid_body),
    ):
        errors = validate_nextdoor_copy(value, property_record, tracked_link)
        if errors:
            raise NextdoorPackageError(f"{label} fact guard blocked the package: " + "; ".join(errors))
    if len(paid_headline) > NEXTDOOR_HEADLINE_LIMIT:
        raise NextdoorPackageError("Nextdoor paid-ad headline exceeds 70 characters.")
    if len(paid_cta) > NEXTDOOR_CTA_LIMIT:
        raise NextdoorPackageError("Nextdoor call to action exceeds 45 characters.")

    return NextdoorPackage(
        business_post_title=title,
        business_post_body=body,
        paid_ad_headline=paid_headline,
        paid_ad_body=paid_body,
        paid_ad_cta=paid_cta,
        tracked_link=tracked_link,
        publication_instructions=(
            "Use a claimed and verified Nextdoor Business Page before publishing a Business Post.",
            "Keep the final Business Post and paid-ad publication manual; do not use browser bots or unsupported auto-posting.",
            "For paid housing ads, obtain manager approval for the budget before launch.",
            "Do not target or imply protected classes, family status, financial hardship, or ZIP-code eligibility for housing.",
            "Use clear property photos and the tracked Dwelyx link. Do not disguise the destination or collect unnecessary personal data.",
            f"Recommended image specifications: {NEXTDOOR_IMAGE_SPECS}",
        ),
    )
