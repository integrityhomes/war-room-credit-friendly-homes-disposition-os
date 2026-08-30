from __future__ import annotations

from typing import Any


class ContractFactsError(RuntimeError):
    """Raised when CommandCore cannot safely prepare contract facts."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(record: dict[str, Any] | None, *keys: str) -> str:
    if not record:
        return ""
    for key in keys:
        value = _text(record.get(key))
        if value:
            return value
    return ""


def _seller_name(seller: dict[str, Any] | None) -> str:
    direct = _first(seller, "name", "full_name", "entity_name")
    if direct:
        return direct
    return " ".join(filter(None, [_first(seller, "first_name"), _first(seller, "last_name")])).strip()


def assemble_contract_facts(
    *,
    deal: dict[str, Any],
    seller: dict[str, Any] | None,
    property_record: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    contract_type = _first(deal, "contract_type")
    state = _first(property_record, "state")
    property_address = _first(property_record, "address", "property_address")
    if not contract_type:
        raise ContractFactsError(
            "Select the contract type before preparing a contract. CommandCore will not guess a legal document type."
        )
    if not state:
        raise ContractFactsError(
            "Property state is required before preparing a contract. CommandCore will not infer legal jurisdiction."
        )
    if not property_address:
        raise ContractFactsError("Property address is required before preparing a contract.")

    facts: dict[str, Any] = {
        "contract_type": contract_type,
        "state": state,
        "property_address": property_address,
        "city": _first(property_record, "city"),
        "zip": _first(property_record, "zip", "zip_code"),
        "legal_description": _first(property_record, "legal_description", "legal"),
        "parcel_number": _first(property_record, "parcel_number", "parcel", "pin"),
        "seller_name": _seller_name(seller),
        "seller_email": _first(seller, "email"),
        "seller_phone": _first(seller, "phone"),
        "purchase_price": _first(deal, "purchase_price", "sales_price", "offer_price"),
        "down_payment": _first(deal, "down_payment"),
        "interest_rate": _first(deal, "interest_rate"),
        "monthly_payment": _first(deal, "monthly_payment", "total_monthly_payment"),
        "monthly_taxes": _first(deal, "monthly_taxes"),
        "monthly_insurance": _first(deal, "monthly_insurance"),
        "insurance_included": _first(deal, "insurance_included"),
        "buyer_1_name": _first(deal, "buyer_1_name", "buyer_name"),
        "buyer_2_name": _first(deal, "buyer_2_name"),
        "first_payment_date": _first(deal, "first_payment_date"),
        "approved_deal_terms_only": True,
    }
    missing = [
        label
        for label, value in {
            "seller name": facts["seller_name"],
            "purchase price": facts["purchase_price"],
            "buyer 1 legal name": facts["buyer_1_name"],
            "legal description": facts["legal_description"],
            "parcel number": facts["parcel_number"],
        }.items()
        if not _text(value)
    ]
    return facts, missing


def contract_prep_document(
    *,
    deal_id: str,
    deal: dict[str, Any],
    seller: dict[str, Any] | None,
    property_record: dict[str, Any] | None,
) -> dict[str, Any]:
    facts, missing = assemble_contract_facts(
        deal=deal,
        seller=seller,
        property_record=property_record,
    )
    return {
        "name": "Contract preparation facts",
        "document_type": "contract_prep_facts",
        "contract_type": facts["contract_type"],
        "status": "needs_missing_facts" if missing else "needs_approved_legal_template",
        "facts": facts,
        "missing_facts": missing,
        "generation_ready": not missing,
        "legal_terms_generated": False,
        "legal_terms_changed": False,
        "signing_started": False,
        "external_action_started": False,
        "source": "commandcore-deal-facts",
        "links": {"deal_id": deal_id},
    }
