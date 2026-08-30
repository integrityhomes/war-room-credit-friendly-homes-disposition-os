from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contract_reader import ContractFact


REVIEW_FACT_LABELS = {
    "seller_name": "Seller",
    "property_address": "Property address",
    "purchase_price": "Purchase price",
    "buyer_1_name": "Buyer 1",
    "buyer_2_name": "Buyer 2",
    "down_payment": "Down payment",
    "interest_rate": "Interest rate",
    "monthly_payment": "Monthly payment",
    "first_payment_date": "First payment date",
    "legal_description": "Legal description",
    "parcel_number": "Parcel number",
    "insurance_included": "Insurance included",
}


def review_facts_from_verified_contract_facts(facts: dict[str, Any]) -> tuple[ContractFact, ...]:
    rows: list[ContractFact] = []
    for key, label in REVIEW_FACT_LABELS.items():
        value = str(facts.get(key) or "").strip()
        rows.append(
            ContractFact(
                key=key,
                label=label,
                expected_value=value,
            )
        )
    return tuple(rows)


def finding_summary(findings: Iterable[Any]) -> dict[str, int]:
    counts = {"found": 0, "needs_review": 0, "missing_deal_fact": 0}
    for finding in findings:
        status = str(getattr(finding, "status", "") or "").strip()
        if status in counts:
            counts[status] += 1
    return counts
