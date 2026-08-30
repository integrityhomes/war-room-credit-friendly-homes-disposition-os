from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationReadiness:
    contract_type: str
    ready: bool
    missing_fields: tuple[str, ...]
    message: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_contract_type(value: str) -> str:
    return " ".join(_text(value).casefold().split())


ILLINOIS_CFD_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("seller_name", "Seller legal name"),
    ("seller_mailing_address", "Seller mailing address"),
    ("seller_formation_state", "Seller formation state"),
    ("property_address", "Property address"),
    ("property_county", "Illinois county"),
    ("legal_description", "Legal description"),
    ("parcel_number", "Parcel number"),
    ("buyer_1_name", "Buyer 1 legal name"),
    ("purchase_price", "Purchase price"),
    ("down_payment", "Down payment"),
    ("interest_rate", "Interest rate"),
    ("number_of_payments", "Number of payments"),
    ("first_payment_date", "First payment date"),
    ("monthly_taxes", "Monthly taxes"),
    ("insurance_included", "Insurance included: Yes or No"),
    ("contract_date", "Contract date"),
    ("payment_payee", "Payment payee"),
    ("payment_address", "Payment address"),
    ("payment_system", "Payment system"),
)

MISSOURI_AFD_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("seller_name", "Seller legal name"),
    ("seller_mailing_address", "Seller mailing address"),
    ("property_address", "Property address"),
    ("buyer_1_name", "Buyer 1 legal name"),
    ("purchase_price", "Purchase price"),
    ("down_payment", "Down payment"),
    ("interest_rate", "Interest rate"),
    ("number_of_payments", "Number of payments"),
    ("first_payment_date", "First payment date"),
    ("monthly_taxes", "Monthly taxes"),
    ("contract_date", "Contract date"),
    ("payment_payee", "Payment payee"),
    ("payment_address", "Payment address"),
    ("payment_system", "Payment system"),
)


def required_fields_for_contract(contract_type: str) -> tuple[tuple[str, str], ...]:
    normalized = _normalized_contract_type(contract_type)
    if "illinois" in normalized and ("contract for deed" in normalized or "cfd" in normalized):
        return ILLINOIS_CFD_REQUIRED_FIELDS
    if "missouri" in normalized and ("agreement for deed" in normalized or "afd" in normalized):
        return MISSOURI_AFD_REQUIRED_FIELDS
    return ()


def generation_readiness(contract_type: str, facts: dict[str, Any]) -> GenerationReadiness:
    required = required_fields_for_contract(contract_type)
    if not required:
        return GenerationReadiness(
            contract_type=_text(contract_type),
            ready=False,
            missing_fields=("Approved generation rules for this contract package",),
            message=(
                "This contract package is not connected to an approved document-generation engine yet. "
                "CommandCore will not guess how to build it."
            ),
        )

    missing = tuple(label for key, label in required if not _text(facts.get(key)))
    if missing:
        return GenerationReadiness(
            contract_type=_text(contract_type),
            ready=False,
            missing_fields=missing,
            message="Complete the missing Deal information before building the contract.",
        )
    return GenerationReadiness(
        contract_type=_text(contract_type),
        ready=True,
        missing_fields=(),
        message="Ready to build from the approved contract template.",
    )
