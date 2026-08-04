from __future__ import annotations

import re
from dataclasses import dataclass, field

from .marketing_claims import risky_condition_claim_errors
from .models import OwnerFinanceProperty


@dataclass(slots=True)
class MarketplaceCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


GUARANTEE_PATTERNS = {
    r"\beveryone\s+(is\s+)?approved\b": "Remove approval guarantees.",
    r"\bguaranteed\s+approval\b": "Remove guaranteed-approval language.",
    r"\bno\s+one\s+(is\s+)?denied\b": "Remove no-denial claims.",
    r"\bcredit\s+doesn['’]?t\s+matter\b": "Avoid absolute credit claims.",
}

FAIR_HOUSING_PATTERNS = {
    r"\bno\s+children\b": "Housing copy cannot state a preference against children.",
    r"\badults?\s+only\b": "Housing copy cannot use adults-only preferences unless a lawful exemption is verified.",
    r"\bperfect\s+for\s+(a\s+)?young\s+couple\b": "Describe the property, not the preferred buyer.",
    r"\bchristian\s+neighbou?rhood\b": "Remove religious preference or neighborhood characterization.",
    r"\benglish\s+speakers?\s+only\b": "Remove national-origin or language preference wording.",
}


def review_marketplace_copy(
    property_record: OwnerFinanceProperty,
    title: str,
    description: str,
    listings_used_this_month: int,
    monthly_limit: int = 5,
) -> MarketplaceCheck:
    result = MarketplaceCheck()
    combined = f"{title}\n{description}".lower()

    if listings_used_this_month >= monthly_limit:
        result.errors.append("Configured monthly Marketplace listing limit has been reached.")

    for pattern, message in {**GUARANTEE_PATTERNS, **FAIR_HOUSING_PATTERNS}.items():
        if re.search(pattern, combined, flags=re.IGNORECASE):
            result.errors.append(message)

    result.errors.extend(risky_condition_claim_errors(combined))

    facts = {
        "total price": property_record.total_price,
        "down payment": property_record.down_payment,
        "monthly payment": property_record.monthly_payment,
    }
    for label, value in facts.items():
        if value is None:
            result.errors.append(f"Property is missing {label}; Marketplace package cannot be prepared.")

    if len(title.strip()) < 15:
        result.warnings.append("Marketplace title may be too short to explain the opportunity clearly.")
    if len(description.strip()) < 100:
        result.warnings.append("Marketplace description may be too short to explain condition and terms.")
    if not property_record.public_disclosures:
        result.errors.append("Public disclosures are required before Marketplace publication.")

    return result
