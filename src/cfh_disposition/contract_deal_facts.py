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
        "property_county": _first(property_record, "county", "property_county"),
        "legal_description": _first(property_record, "legal_description", "legal"),
        "parcel_number": _first(property_record, "parcel_number", "parcel", "pin", "parcel_id"),
        "assessed_value": _first(property_record, "assessed_value"),
        "fair_cash_value": _first(property_record, "fair_cash_value"),
        "last_tax_bill": _first(property_record, "last_tax_bill", "annual_taxes"),
        "seller_name": _seller_name(seller),
        "seller_email": _first(seller, "email"),
        "seller_phone": _first(seller, "phone"),
        "seller_mailing_address": _first(
            seller,
            "mailing_address",
            "address",
            "seller_mailing_address",
        ),
        "seller_formation_state": _first(
            seller,
            "formation_state",
            "state_of_formation",
            "seller_formation_state",
        ),
        "purchase_price": _first(deal, "purchase_price", "sales_price", "offer_price"),
        "down_payment": _first(deal, "down_payment"),
        "amount_financed": _first(deal, "amount_financed", "financed_amount"),
        "interest_rate": _first(deal, "interest_rate"),
        "apr": _first(deal, "apr"),
        "number_of_payments": _first(deal, "number_of_payments", "payment_count", "term_months"),
        "monthly_payment": _first(deal, "monthly_payment", "total_monthly_payment"),
        "monthly_principal_interest": _first(deal, "monthly_principal_interest", "monthly_pi"),
        "monthly_taxes": _first(deal, "monthly_taxes"),
        "monthly_insurance": _first(deal, "monthly_insurance"),
        "monthly_servicing_fee": _first(deal, "monthly_servicing_fee"),
        "conversion_rent": _first(deal, "conversion_rent", "conversion_rent_after_termination"),
        "insurance_included": _first(deal, "insurance_included"),
        "buyer_1_name": _first(deal, "buyer_1_name", "buyer_name"),
        "buyer_2_name": _first(deal, "buyer_2_name"),
        "buyer_1_email": _first(deal, "buyer_1_email", "buyer_email"),
        "buyer_2_email": _first(deal, "buyer_2_email"),
        "buyer_1_phone": _first(deal, "buyer_1_phone", "buyer_phone"),
        "buyer_2_phone": _first(deal, "buyer_2_phone"),
        "buyer_use_primary": bool(deal.get("buyer_use_primary", False)),
        "buyer_use_investment": bool(deal.get("buyer_use_investment", False)),
        "buyer_use_fix_flip": bool(deal.get("buyer_use_fix_flip", False)),
        "buyer_use_family": bool(deal.get("buyer_use_family", False)),
        "buyer_use_short_term": bool(deal.get("buyer_use_short_term", False)),
        "buyer_use_landlord": bool(deal.get("buyer_use_landlord", False)),
        "buyer_use_other": bool(deal.get("buyer_use_other", False)),
        "buyer_use_other_text": _first(deal, "buyer_use_other_text"),
        "contract_date": _first(deal, "contract_date"),
        "notice_date": _first(deal, "notice_date"),
        "earliest_execution_date": _first(deal, "earliest_execution_date"),
        "disclosure_date": _first(deal, "disclosure_date"),
        "deed_date": _first(deal, "deed_date"),
        "memorandum_date": _first(deal, "memorandum_date"),
        "possession_date": _first(deal, "possession_date"),
        "first_payment_date": _first(deal, "first_payment_date"),
        "payment_payee": _first(deal, "payment_payee"),
        "payment_address": _first(deal, "payment_address"),
        "payment_system": _first(deal, "payment_system"),
        "escrow_agent_name": _first(deal, "escrow_agent_name"),
        "escrow_agent_address": _first(deal, "escrow_agent_address"),
        "current_lien_disclosure": _first(deal, "current_lien_disclosure"),
        "closing_costs": _first(deal, "closing_costs"),
        "grace_period_days": _first(deal, "grace_period_days"),
        "late_fee_percent": _first(deal, "late_fee_percent"),
        "last_insurance_bill": _first(deal, "last_insurance_bill"),
        "tax_year": _first(deal, "tax_year"),
        "tax_payable_year": _first(deal, "tax_payable_year"),
        "special_assessment_year": _first(deal, "special_assessment_year"),
        "finance_charge": _first(deal, "finance_charge"),
        "total_of_payments": _first(deal, "total_of_payments"),
        "disclosure_yes_questions": deal.get("disclosure_yes_questions") or [],
        "disclosure_explanation": _first(deal, "disclosure_explanation"),
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
