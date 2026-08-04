from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from .marketing_claims import risky_condition_claim_errors
from .meta_marketplace_policy import (
    META_MARKETPLACE_POLICY_VERSION,
    REQUIRED_MARKETPLACE_DISCLOSURES,
    marketplace_disclaimer,
    meta_marketplace_policy_errors,
    meta_marketplace_policy_warnings,
)
from .models import OwnerFinanceProperty

URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", flags=re.IGNORECASE)


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


def _decimal_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(value: Any) -> str:
    number = _decimal_value(value)
    return "Not provided" if number is None else f"${number:,.0f}"


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _marketing_address(property_record: OwnerFinanceProperty) -> str:
    city_state = ", ".join(
        part for part in [str(property_record.city or ""), str(property_record.state or "")] if part
    )
    locality = f"{city_state} {str(property_record.zip_code or '')}".strip()
    return ", ".join(
        part for part in [str(property_record.address or ""), locality] if part
    )


def build_meta_safe_marketplace_package(
    property_record: OwnerFinanceProperty,
    tracked_dwelyx_link: str = "",
) -> MarketplacePackage:
    """Build conservative Marketplace copy with no public external link."""
    address = _marketing_address(property_record)
    title = f"Owner-Finance Home — {address}" if address else "Owner-Finance Home Available"
    condition = str(property_record.condition_summary or "").strip() or (
        "Condition details must be confirmed during review."
    )
    repairs = str(property_record.repairs_needed or "").strip() or (
        "No repairs statement was provided. Buyers should verify the property's condition during review."
    )
    disclosures = str(property_record.public_disclosures or "").strip() or (
        "Property information and terms must be verified."
    )
    description = (
        f"{address}\n\n"
        f"{property_record.bedrooms or '—'} bed / {property_record.bathrooms or '—'} bath\n"
        "Owner-finance opportunity. The monthly payment shown is not rent.\n"
        f"Down payment: {_money(property_record.down_payment)}\n"
        f"Monthly owner-finance payment: {_money(property_record.monthly_payment)}\n\n"
        f"Condition: {condition}\n\n"
        f"Known repairs or work needed: {repairs}\n\n"
        f"Disclosures: {disclosures}\n\n"
        f"{marketplace_disclaimer()}\n\n"
        "Send us a Facebook Marketplace message for complete purchase terms, property questions, and next steps."
    )
    return MarketplacePackage(title=title, description=description)


def _money_is_present(text: str, value: Any) -> bool:
    number = _decimal_value(value)
    if number is None:
        return False
    formatted = f"${number:,.0f}"
    plain = f"${number:.0f}"
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
    title = str(title or "")
    description = str(description or "")
    listings_used = max(_int_value(listings_used_this_month, 0), 0)
    limit = max(_int_value(monthly_limit, 5), 1)
    combined = f"{title}\n{description}"

    if listings_used >= limit:
        result.errors.append(
            "Internal posting-safety limit reached. Pause and review account health before another Marketplace listing."
        )

    result.errors.extend(meta_marketplace_policy_errors(combined))
    result.errors.extend(risky_condition_claim_errors(combined))
    result.warnings.extend(meta_marketplace_policy_warnings(combined))

    if URL_PATTERN.search(combined):
        result.errors.append(
            "Remove all website links from the Facebook Marketplace title and description. "
            "Keep the conversation inside Facebook Marketplace or Messenger first."
        )
    if tracked_dwelyx_link and str(tracked_dwelyx_link) in combined:
        result.errors.append(
            "Do not place the tracked Dwelyx buyer link directly in Facebook Marketplace copy."
        )

    address = _marketing_address(property_record)
    if address and address.lower() not in combined.lower():
        result.errors.append(
            "The complete property address must appear in the Marketplace package."
        )

    required_public_terms = {
        "down payment": property_record.down_payment,
        "monthly payment": property_record.monthly_payment,
    }
    for label, value in required_public_terms.items():
        if _decimal_value(value) is None:
            result.errors.append(
                f"Property is missing {label}; Marketplace package cannot be prepared."
            )
        elif not _money_is_present(description, value):
            result.errors.append(
                f"The exact {label} must appear in the Marketplace description."
            )

    if _decimal_value(property_record.total_price) is None:
        result.errors.append("Property is missing total price in the internal record.")
    elif _money_is_present(description, property_record.total_price):
        result.errors.append(
            "Remove the total purchase price from the public Marketplace description. "
            "Keep full purchase terms in the internal record and buyer follow-up."
        )

    if "not rent" not in description.lower():
        result.errors.append(
            'Marketplace copy must clearly state that the monthly owner-finance payment is "not rent."'
        )

    if "facebook marketplace message" not in description.lower():
        result.errors.append(
            "Marketplace copy must tell buyers to send a Facebook Marketplace message instead of directing them off-platform."
        )

    condition_summary = str(property_record.condition_summary or "")
    repairs_needed = str(property_record.repairs_needed or "")
    public_disclosures = str(property_record.public_disclosures or "")

    if condition_summary and condition_summary.lower() not in description.lower():
        result.warnings.append(
            "The saved condition summary is not quoted exactly. Confirm that no condition facts were changed."
        )
    if repairs_needed and repairs_needed.lower() not in description.lower():
        result.warnings.append(
            "The saved repairs statement is not quoted exactly. Confirm that no known work was omitted."
        )

    if not public_disclosures:
        result.errors.append(
            "Public disclosures are required before Marketplace publication."
        )
    elif public_disclosures.lower() not in description.lower():
        result.errors.append(
            "The saved public disclosures must appear in the Marketplace description."
        )

    for disclosure in REQUIRED_MARKETPLACE_DISCLOSURES:
        if disclosure.lower() not in description.lower():
            result.errors.append(
                f'Required Marketplace disclosure is missing: "{disclosure}"'
            )

    if len(title.strip()) < 15:
        result.warnings.append(
            "Marketplace title may be too short to explain the opportunity clearly."
        )
    if len(description.strip()) < 250:
        result.warnings.append(
            "Marketplace description may be too short to explain the property facts, condition, terms, and disclosures."
        )

    result.errors = sorted(set(result.errors))
    result.warnings = sorted(set(result.warnings))
    return result
