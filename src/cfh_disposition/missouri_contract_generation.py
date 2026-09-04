from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from .contract_document_renderer import build_amortization_schedule
from .contract_generation_pipeline import (
    DOCX_CONTENT_TYPE,
    ContractGenerationError,
    GeneratedContract,
    calculate_monthly_principal_interest,
    next_generated_version,
    select_exact_approved_template,
)
from .contract_generation_readiness import generation_readiness
from .contract_workspace import ContractFile, ContractFileStore, DocumentPurpose, document_record
from .missouri_contract_renderer import build_missouri_contract_context, generate_missouri_contract_document

MISSOURI_GENERATION_ENGINE = "commandcore-mo-afd-v14"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, *, field_name: str = "value") -> float:
    if value is None or value == "":
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in {"", ".", "-", "-."}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ContractGenerationError(f"{field_name} is not a valid number.") from exc


def _integer(value: Any, *, field_name: str) -> int:
    number = _number(value, field_name=field_name)
    if number != int(number):
        raise ContractGenerationError(f"{field_name} must be a whole number.")
    return int(number)


def _date(value: Any, *, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _text(value)
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(raw, pattern).date()
        except ValueError:
            continue
    raise ContractGenerationError(f"{field_name} must be a valid date.")


def is_missouri_afd(value: Any) -> bool:
    normalized = " ".join(_text(value).casefold().split())
    return "missouri" in normalized and ("agreement for deed" in normalized or "afd" in normalized)


def _build_missouri_inputs(facts: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    contract_type = _text(facts.get("contract_type"))
    readiness = generation_readiness(contract_type, facts)
    if not readiness.ready:
        raise ContractGenerationError(f"{readiness.message} Missing: {', '.join(readiness.missing_fields)}")
    if not is_missouri_afd(contract_type):
        raise ContractGenerationError("This renderer supports Missouri Agreement for Deed packages only.")
    if _text(facts.get("state")).upper() != "MO":
        raise ContractGenerationError("Missouri Agreement for Deed generation requires a Missouri property.")

    contract_date = _date(facts.get("contract_date"), field_name="Contract date")
    first_payment_date = _date(facts.get("first_payment_date"), field_name="First payment date")
    sales_price = _number(facts.get("purchase_price"), field_name="Purchase price")
    down_payment = _number(facts.get("down_payment"), field_name="Down payment")
    amount_financed = _number(facts.get("amount_financed"), field_name="Amount financed") or max(
        sales_price - down_payment,
        0.0,
    )
    annual_interest_rate = _number(facts.get("interest_rate"), field_name="Interest rate")
    number_of_payments = _integer(facts.get("number_of_payments"), field_name="Number of payments")
    monthly_principal_interest = _number(
        facts.get("monthly_principal_interest"),
        field_name="Monthly principal and interest",
    ) or calculate_monthly_principal_interest(amount_financed, annual_interest_rate, number_of_payments)
    monthly_taxes = _number(facts.get("monthly_taxes"), field_name="Monthly taxes")

    listed_total = _number(facts.get("monthly_payment"), field_name="Total monthly payment")
    monthly_servicing_fee = _number(facts.get("monthly_servicing_fee"), field_name="Monthly servicing fee")
    if not _text(facts.get("monthly_servicing_fee")) and listed_total > 0:
        monthly_servicing_fee = max(listed_total - monthly_principal_interest - monthly_taxes, 0.0)
    total_monthly_payment = monthly_principal_interest + monthly_taxes + monthly_servicing_fee
    conversion_rent = _number(facts.get("conversion_rent"), field_name="Conversion rent")
    if not _text(facts.get("conversion_rent")):
        conversion_rent = listed_total or total_monthly_payment

    if amount_financed <= 0:
        raise ContractGenerationError("Amount financed must be greater than zero.")
    if down_payment >= sales_price:
        raise ContractGenerationError("Down payment must be less than the sales price.")

    scheduled_total = monthly_principal_interest * number_of_payments
    finance_charge = _number(facts.get("finance_charge"), field_name="Finance charge") or max(
        scheduled_total - amount_financed,
        0.0,
    )
    total_of_payments = _number(facts.get("total_of_payments"), field_name="Total of payments") or scheduled_total
    apr = _number(facts.get("apr"), field_name="APR") or annual_interest_rate
    late_fee_percent = (
        _number(facts.get("late_fee_percent"), field_name="Late fee percent")
        if _text(facts.get("late_fee_percent"))
        else 10.0
    )
    grace_period_days = (
        _integer(facts.get("grace_period_days"), field_name="Grace period")
        if _text(facts.get("grace_period_days"))
        else 5
    )

    context = build_missouri_contract_context(
        property_address=_text(facts.get("property_address")),
        seller_name=_text(facts.get("seller_name")),
        seller_address=_text(facts.get("seller_mailing_address")),
        buyer_1_name=_text(facts.get("buyer_1_name")),
        buyer_2_name=_text(facts.get("buyer_2_name")),
        buyer_1_email=_text(facts.get("buyer_1_email")),
        buyer_2_email=_text(facts.get("buyer_2_email")),
        buyer_1_phone=_text(facts.get("buyer_1_phone")),
        buyer_2_phone=_text(facts.get("buyer_2_phone")),
        contract_date=contract_date,
        first_payment_date=first_payment_date,
        sales_price=sales_price,
        down_payment=down_payment,
        amount_financed=amount_financed,
        annual_interest_rate=annual_interest_rate,
        number_of_payments=number_of_payments,
        monthly_principal_interest=monthly_principal_interest,
        monthly_taxes=monthly_taxes,
        monthly_servicing_fee=monthly_servicing_fee,
        total_monthly_payment=total_monthly_payment,
        conversion_rent=conversion_rent,
        payment_payee=_text(facts.get("payment_payee")),
        payment_address=_text(facts.get("payment_address")),
        payment_system=_text(facts.get("payment_system")),
        late_fee_percent=late_fee_percent,
        grace_period_days=grace_period_days,
        apr=apr,
        finance_charge=finance_charge,
        total_of_payments=total_of_payments,
        use_primary=bool(facts.get("buyer_use_primary")),
        use_investment=bool(facts.get("buyer_use_investment")),
        use_fix_flip=bool(facts.get("buyer_use_fix_flip")),
        use_family=bool(facts.get("buyer_use_family")),
        use_short_term=bool(facts.get("buyer_use_short_term")),
        use_landlord=bool(facts.get("buyer_use_landlord")),
        use_other=bool(facts.get("buyer_use_other")),
        use_other_text=_text(facts.get("buyer_use_other_text")),
    )
    schedule = build_amortization_schedule(
        principal=amount_financed,
        annual_interest_rate=annual_interest_rate,
        number_of_payments=number_of_payments,
        first_payment_date=first_payment_date,
        monthly_principal_interest=monthly_principal_interest,
        monthly_taxes=monthly_taxes,
        monthly_insurance=0.0,
    )
    return context, schedule


def generate_and_store_missouri_contract(
    *,
    client: Any,
    deal_id: str,
    facts_document: dict[str, Any],
    all_documents: list[dict[str, Any]],
) -> GeneratedContract:
    facts = facts_document.get("facts") if isinstance(facts_document.get("facts"), dict) else {}
    contract_type = _text(facts_document.get("contract_type") or facts.get("contract_type"))
    state = _text(facts.get("state"))
    if not contract_type or not state:
        raise ContractGenerationError("Contract package and property state are required before generation.")
    if not is_missouri_afd(contract_type) or state.upper() != "MO":
        raise ContractGenerationError("Missouri Agreement for Deed generation requires an exact Missouri package and property.")

    template = select_exact_approved_template(all_documents, contract_type=contract_type, state=state)
    template_id = _text(template.get("id"))
    if not template_id:
        raise ContractGenerationError("The approved Missouri template record is missing its document ID.")

    store = ContractFileStore(client)
    template_bytes = store.download(_text(template.get("storage_object_path")))
    context, schedule = _build_missouri_inputs(facts)
    generated_bytes = generate_missouri_contract_document(
        template_bytes=template_bytes,
        context=context,
        amortization_schedule=schedule,
    )

    version = next_generated_version(all_documents, deal_id=deal_id, contract_type=contract_type)
    address_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", _text(facts.get("property_address"))).strip("_") or "Property"
    output_file = ContractFile(
        file_name=f"{address_slug}_Completed_Missouri_Agreement_for_Deed.docx",
        content=generated_bytes,
        content_type=DOCX_CONTENT_TYPE,
    )
    stored = store.upload(
        deal_id=deal_id,
        purpose=DocumentPurpose.GENERATED_CONTRACT,
        version=version,
        file=output_file,
    )
    record = document_record(
        deal_id=deal_id,
        purpose=DocumentPurpose.GENERATED_CONTRACT,
        stored=stored,
        version=version,
        template_family=contract_type,
        template_version=_text(template.get("template_version") or template.get("version")),
    )
    record.update(
        {
            "status": "generated_needs_review",
            "contract_type": contract_type,
            "state": "MO",
            "source": "commandcore-contract-builder",
            "generation_engine": MISSOURI_GENERATION_ENGINE,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_facts_document_id": _text(facts_document.get("id")) or None,
            "approved_legal_template_id": template_id,
            "approved_template_reference": {
                "document_id": template_id,
                "name": _text(template.get("name")) or None,
                "version": template.get("version"),
                "template_version": _text(template.get("template_version")) or None,
                "state": _text(template.get("state")),
                "contract_type": _text(template.get("contract_type")),
                "legal_review_status": _text(template.get("legal_review_status")),
                "approved_for_use": True,
            },
            "insurance_version": "not_applicable",
            "insurance_clause_changes": [],
            "document_assembled": True,
            "approval_required": True,
            "owner_approval_required": True,
            "legal_terms_generated": False,
            "legal_terms_changed": False,
            "legal_terms_changed_by_commandcore": False,
            "signing_started": False,
            "external_action_started": False,
            "generation_provenance": {
                "facts_document_id": _text(facts_document.get("id")) or None,
                "template_document_id": template_id,
                "template_version": template.get("version"),
                "engine": MISSOURI_GENERATION_ENGINE,
                "immutable_version": version,
            },
        }
    )
    activity = {
        "activity_type": "contract_generated",
        "title": "Contract generated for review",
        "summary": (
            f"{contract_type} v{version} generated from approved template version {template.get('version')} "
            "using the proven Missouri Agreement for Deed renderer."
        ),
        "source": "commandcore-contract-builder",
        "details": {
            "generated_document_version": version,
            "template_document_id": template_id,
            "template_version": template.get("version"),
            "facts_document_id": _text(facts_document.get("id")) or None,
            "generation_engine": MISSOURI_GENERATION_ENGINE,
            "signing_started": False,
            "external_action_started": False,
        },
        "links": {"deal_id": deal_id},
    }
    return GeneratedContract(
        document_record=record,
        activity_record=activity,
        generated_bytes=generated_bytes,
        template_id=template_id,
        template_version=_text(template.get("template_version") or template.get("version")),
        insurance_version="not_applicable",
    )
