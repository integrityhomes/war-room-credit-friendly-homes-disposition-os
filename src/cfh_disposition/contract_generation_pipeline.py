from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import holidays
from dateutil.relativedelta import relativedelta

from .contract_document_renderer import build_amortization_schedule, format_currency, generate_contract_document
from .contract_generation_readiness import generation_readiness
from .contract_insurance_control import insurance_amount_for_payment, insurance_version_label, normalize_insurance_included
from .contract_workspace import ContractFile, ContractFileStore, DocumentPurpose, document_record

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GENERATION_ENGINE = "commandcore-il-cfd-v14"


class ContractGenerationError(RuntimeError):
    """Raised when a contract cannot be generated safely from approved inputs."""


@dataclass(frozen=True, slots=True)
class GeneratedContract:
    document_record: dict[str, Any]
    activity_record: dict[str, Any]
    generated_bytes: bytes
    template_id: str
    template_version: str
    insurance_version: str


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


def _full_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def _percentage(value: float) -> str:
    return f"{value:.4f}%"


def _combine(values: list[str], separator: str = " and ") -> str:
    return separator.join(value.strip() for value in values if value.strip())


def _split_address(address: str) -> tuple[str, str]:
    normalized = " ".join(address.split())
    parts = [part.strip() for part in normalized.split(",")]
    if len(parts) >= 3:
        return parts[0], ", ".join(parts[1:])
    return normalized, ""


_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _state_name(value: str) -> str:
    cleaned = _text(value)
    return _STATE_NAMES.get(cleaned.upper(), cleaned)


def _normalized_contract_type(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def is_illinois_cfd(value: Any) -> bool:
    normalized = _normalized_contract_type(value)
    return "illinois" in normalized and ("contract for deed" in normalized or "cfd" in normalized)


def _approved_template(record: dict[str, Any]) -> bool:
    document_type = _text(record.get("document_type")).casefold()
    status = _text(record.get("status")).casefold()
    legal_status = _text(record.get("legal_review_status")).casefold()
    return (
        document_type in {"approved_legal_template", "contract_template"}
        and status in {"approved", "active", "owner_approved"}
        and record.get("approved_for_use") is True
        and (record.get("legal_approved") is True or legal_status == "approved")
        and bool(_text(record.get("storage_object_path")))
    )


def select_exact_approved_template(
    documents: list[dict[str, Any]],
    *,
    contract_type: str,
    state: str,
) -> dict[str, Any]:
    matches = [
        record
        for record in documents
        if _approved_template(record)
        and _normalized_contract_type(record.get("contract_type")) == _normalized_contract_type(contract_type)
        and _text(record.get("state")).upper() == _text(state).upper()
    ]
    if not matches:
        raise ContractGenerationError("No explicitly approved contract template exactly matches this contract package and state.")

    def version(record: dict[str, Any]) -> int:
        try:
            return int(record.get("version") or 0)
        except (TypeError, ValueError):
            return 0

    return max(matches, key=version)


def next_generated_version(documents: list[dict[str, Any]], *, deal_id: str, contract_type: str) -> int:
    versions: list[int] = []
    for record in documents:
        links = record.get("links") if isinstance(record.get("links"), dict) else {}
        if _text(links.get("deal_id") or record.get("deal_id")) != _text(deal_id):
            continue
        if _text(record.get("document_type")) != DocumentPurpose.GENERATED_CONTRACT.value:
            continue
        if _normalized_contract_type(record.get("contract_type")) != _normalized_contract_type(contract_type):
            continue
        try:
            versions.append(int(record.get("version") or 0))
        except (TypeError, ValueError):
            continue
    return max(versions, default=0) + 1


def calculate_monthly_principal_interest(principal: float, annual_interest_rate: float, number_of_payments: int) -> float:
    if principal <= 0 or number_of_payments <= 0:
        return 0.0
    monthly_interest_rate = annual_interest_rate / 100 / 12
    if monthly_interest_rate == 0:
        return principal / number_of_payments
    growth_factor = (1 + monthly_interest_rate) ** number_of_payments
    return principal * (monthly_interest_rate * growth_factor) / (growth_factor - 1)


def earliest_illinois_execution_date(notice_date: date, full_business_days: int = 3) -> date:
    calendar = holidays.country_holidays("US", subdiv="IL", years=[notice_date.year, notice_date.year + 1], observed=True)
    current = notice_date
    counted = 0
    while counted < full_business_days:
        current += timedelta(days=1)
        if current.weekday() < 5 and current not in calendar:
            counted += 1
    current += timedelta(days=1)
    while current.weekday() >= 5 or current in calendar:
        current += timedelta(days=1)
    return current


def _current_lien_disclosure(facts: dict[str, Any]) -> str:
    explicit = _text(facts.get("current_lien_disclosure"))
    if explicit:
        return explicit
    lender = _text(facts.get("lender"))
    if not lender or lender.casefold() in {"no", "none", "n/a", "na", "false", "0", "no lender"}:
        return "Not Applicable"
    county = _text(facts.get("property_county"))
    county = re.sub(r"[,\s]+Illinois$", "", county, flags=re.IGNORECASE).strip(" ,")
    if county and not county.casefold().endswith(" county"):
        county = f"{county} County"
    if not county:
        raise ContractGenerationError("Illinois county is required to build the current lien disclosure.")
    return f"A mortgage exists and is recorded in the Recorder's Office of {county}, Illinois."


def _build_v14_inputs(facts: dict[str, Any]) -> tuple[dict[str, Any], Any, str]:
    readiness = generation_readiness(_text(facts.get("contract_type")), facts)
    if not readiness.ready:
        raise ContractGenerationError(f"{readiness.message} Missing: {', '.join(readiness.missing_fields)}")
    if not is_illinois_cfd(facts.get("contract_type")):
        raise ContractGenerationError("This approved renderer currently supports Illinois Contract for Deed packages only.")
    if _text(facts.get("state")).upper() != "IL":
        raise ContractGenerationError("Illinois CFD generation requires an Illinois property.")

    contract_date = _date(facts.get("contract_date"), field_name="Contract date")
    first_payment_date = _date(facts.get("first_payment_date"), field_name="First payment date")
    notice_date = _date(facts.get("notice_date"), field_name="Notice date") if _text(facts.get("notice_date")) else contract_date
    disclosure_date = _date(facts.get("disclosure_date"), field_name="Disclosure date") if _text(facts.get("disclosure_date")) else contract_date
    possession_date = _date(facts.get("possession_date"), field_name="Possession date") if _text(facts.get("possession_date")) else contract_date
    memorandum_date = _date(facts.get("memorandum_date"), field_name="Memorandum date") if _text(facts.get("memorandum_date")) else contract_date
    earliest_execution = (
        _date(facts.get("earliest_execution_date"), field_name="Earliest execution date")
        if _text(facts.get("earliest_execution_date"))
        else earliest_illinois_execution_date(notice_date)
    )
    deed_date = _date(facts.get("deed_date"), field_name="Deed date") if _text(facts.get("deed_date")) else earliest_execution

    sales_price = _number(facts.get("purchase_price"), field_name="Purchase price")
    down_payment = _number(facts.get("down_payment"), field_name="Down payment")
    amount_financed = _number(facts.get("amount_financed"), field_name="Amount financed") or max(sales_price - down_payment, 0.0)
    interest_rate = _number(facts.get("interest_rate"), field_name="Interest rate")
    apr = _number(facts.get("apr"), field_name="APR") or interest_rate
    number_of_payments = _integer(facts.get("number_of_payments"), field_name="Number of payments")
    monthly_pi = calculate_monthly_principal_interest(amount_financed, interest_rate, number_of_payments)
    monthly_taxes = _number(facts.get("monthly_taxes"), field_name="Monthly taxes")
    insurance_status = normalize_insurance_included(facts.get("insurance_included"))
    monthly_insurance = insurance_amount_for_payment(_number(facts.get("monthly_insurance"), field_name="Monthly insurance"), insurance_status)
    total_monthly_payment = monthly_pi + monthly_taxes + monthly_insurance
    last_insurance_bill = _number(facts.get("last_insurance_bill"), field_name="Last annual insurance bill")
    if last_insurance_bill <= 0 and monthly_insurance > 0:
        last_insurance_bill = monthly_insurance * 12

    if amount_financed <= 0:
        raise ContractGenerationError("Amount financed must be greater than zero.")
    if down_payment >= sales_price:
        raise ContractGenerationError("Down payment must be less than the sales price.")
    if interest_rate > 12:
        raise ContractGenerationError("Interest rate is above 12% and requires approval before contract generation.")

    scheduled_pi_total = monthly_pi * number_of_payments
    scheduled_interest_total = max(scheduled_pi_total - amount_financed, 0.0)
    finance_charge = _number(facts.get("finance_charge"), field_name="Finance charge") or scheduled_interest_total
    total_of_payments = _number(facts.get("total_of_payments"), field_name="Total of payments") or scheduled_pi_total

    closing_costs = _number(facts.get("closing_costs"), field_name="Closing costs") if _text(facts.get("closing_costs")) else 200.0
    grace_days = _integer(facts.get("grace_period_days"), field_name="Grace period") if _text(facts.get("grace_period_days")) else 5
    late_fee_percent = _number(facts.get("late_fee_percent"), field_name="Late fee percent") if _text(facts.get("late_fee_percent")) else 10.0
    tax_year = _integer(facts.get("tax_year"), field_name="Tax year") if _text(facts.get("tax_year")) else contract_date.year
    tax_payable_year = _integer(facts.get("tax_payable_year"), field_name="Tax payable year") if _text(facts.get("tax_payable_year")) else contract_date.year + 1
    special_assessment_year = (
        _integer(facts.get("special_assessment_year"), field_name="Special assessment year")
        if _text(facts.get("special_assessment_year"))
        else contract_date.year
    )

    buyer_names = _combine([_text(facts.get("buyer_1_name")), _text(facts.get("buyer_2_name"))])
    buyer_emails = _combine([_text(facts.get("buyer_1_email")), _text(facts.get("buyer_2_email"))], "; ")
    buyer_phones = _combine([_text(facts.get("buyer_1_phone")), _text(facts.get("buyer_2_phone"))], "; ")
    property_street, property_city_state_zip = _split_address(_text(facts.get("property_address")))
    seller_address_line1, seller_city_state_zip = _split_address(_text(facts.get("seller_mailing_address")))
    loan_years = number_of_payments / 12
    loan_term = f"{number_of_payments} months ({int(loan_years)} years)" if float(loan_years).is_integer() else f"{number_of_payments} months"
    payment_due_description = f"Monthly, beginning {_full_date(first_payment_date)}, and due on the 1st day of each month thereafter"
    payment_payee = _text(facts.get("payment_payee"))
    payment_address = _text(facts.get("payment_address"))
    escrow_agent_name = _text(facts.get("escrow_agent_name")) or payment_payee
    escrow_agent_address = _text(facts.get("escrow_agent_address")) or payment_address
    if not escrow_agent_name or not escrow_agent_address:
        raise ContractGenerationError("Escrow agent name and address are required before generating the Illinois CFD package.")

    context: dict[str, Any] = {
        "AG_NOTICE_DATE": _full_date(notice_date),
        "AMORTIZATION_SCHEDULE": "[[AMORTIZATION_TABLE]]",
        "AMOUNT_FINANCED": format_currency(amount_financed),
        "APR": _percentage(apr),
        "ASSESSED_VALUE": _text(facts.get("assessed_value")),
        "BUYER_1_NAME": _text(facts.get("buyer_1_name")),
        "BUYER_2_NAME": _text(facts.get("buyer_2_name")),
        "BUYER_EMAILS": buyer_emails,
        "BUYER_NAMES_AND_PROPERTY_ADDRESS": f"{buyer_names}, {_text(facts.get('property_address'))}",
        "BUYER_NAMES": buyer_names,
        "BUYER_PHONES": buyer_phones,
        "CLOSING_COSTS": format_currency(closing_costs),
        "CONTRACT_DATE": _full_date(contract_date),
        "CURRENT_LIEN_DISCLOSURE": _current_lien_disclosure(facts),
        "DAYS_TO_YEAR_END": str(max((date(contract_date.year, 12, 31) - contract_date).days + 1, 0)),
        "DEED_DATE": _full_date(deed_date),
        "DISCLOSURE_DATE": _full_date(disclosure_date),
        "DOWN_PAYMENT": format_currency(down_payment),
        "EARLIEST_EXECUTION_DATE": _full_date(earliest_execution),
        "ESCROW_AGENT_ADDRESS": escrow_agent_address,
        "ESCROW_AGENT_NAME": escrow_agent_name,
        "FAIR_CASH_VALUE": _text(facts.get("fair_cash_value")),
        "FINANCE_CHARGE": format_currency(finance_charge),
        "FIRST_PAYMENT_DATE": _full_date(first_payment_date),
        "GRACE_PERIOD_DAYS": str(grace_days),
        "INTEREST_RATE": _percentage(interest_rate),
        "INTEREST_START_DATE": _full_date(contract_date),
        "LAST_INSURANCE_BILL": format_currency(last_insurance_bill),
        "LAST_TAX_BILL": _text(facts.get("last_tax_bill")),
        "LATE_FEE_PERCENT": f"{late_fee_percent:g}%",
        "LATE_PAYMENT_CHARGE": f"{late_fee_percent:g}% of the overdue installment after {grace_days} days",
        "LEGAL_DESCRIPTION": _text(facts.get("legal_description")),
        "LOAN_TERM": loan_term,
        "MEMORANDUM_DATE": _full_date(memorandum_date),
        "MONTHLY_INSURANCE": format_currency(monthly_insurance),
        "MONTHLY_PRINCIPAL_INTEREST": format_currency(monthly_pi),
        "MONTHLY_TAXES": format_currency(monthly_taxes),
        "NUMBER_OF_PAYMENTS": str(number_of_payments),
        "PARCEL_NUMBER": _text(facts.get("parcel_number")),
        "PAYMENT_ADDRESS": payment_address,
        "PAYMENT_DUE_DESCRIPTION": payment_due_description,
        "PAYMENT_PAYEE": payment_payee,
        "PAYMENT_SYSTEM": _text(facts.get("payment_system")),
        "POSSESSION_DATE": _full_date(possession_date),
        "PROPERTY_ADDRESS": _text(facts.get("property_address")),
        "PROPERTY_CITY_STATE_ZIP": property_city_state_zip,
        "PROPERTY_COUNTY": _text(facts.get("property_county")),
        "PROPERTY_STREET_ADDRESS": property_street,
        "SALES_PRICE": format_currency(sales_price),
        "SELLER_MAILING_ADDRESS_LINE1": seller_address_line1,
        "SELLER_MAILING_CITY_STATE_ZIP": seller_city_state_zip,
        "SELLER_NAME": _text(facts.get("seller_name")),
        "SELLER_STATE": _state_name(_text(facts.get("seller_formation_state"))),
        "SPECIAL_ASSESSMENT_YEAR": str(special_assessment_year),
        "TAX_PAYABLE_YEAR": str(tax_payable_year),
        "TAX_YEAR": str(tax_year),
        "TOTAL_MONTHLY_PAYMENT": format_currency(total_monthly_payment),
        "TOTAL_OF_PAYMENTS": format_currency(total_of_payments),
        "_INSURANCE_STATUS": insurance_status,
        "_PRIOR_YEAR_INSURANCE_KNOWN": last_insurance_bill > 0,
    }
    schedule = build_amortization_schedule(
        amount_financed,
        interest_rate,
        number_of_payments,
        first_payment_date,
        monthly_pi,
        monthly_taxes,
        monthly_insurance,
    )
    return context, schedule, insurance_version_label(insurance_status)


def generate_and_store_contract(
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
    template = select_exact_approved_template(all_documents, contract_type=contract_type, state=state)
    template_id = _text(template.get("id"))
    if not template_id:
        raise ContractGenerationError("The approved template record is missing its document ID.")

    store = ContractFileStore(client)
    template_bytes = store.download(_text(template.get("storage_object_path")))
    context, schedule, insurance_version = _build_v14_inputs(facts)
    generated_bytes, insurance_changes = generate_contract_document(
        template_bytes=template_bytes,
        context=context,
        amortization_schedule=schedule,
        disclosure_yes_questions=facts.get("disclosure_yes_questions") or (),
        disclosure_explanation=_text(facts.get("disclosure_explanation")),
    )

    version = next_generated_version(all_documents, deal_id=deal_id, contract_type=contract_type)
    address_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", _text(facts.get("property_address"))).strip("_") or "Property"
    output_file = ContractFile(
        file_name=f"{address_slug}_Completed_Illinois_CFD.docx",
        content=generated_bytes,
        content_type=DOCX_CONTENT_TYPE,
    )
    stored = store.upload(deal_id=deal_id, purpose=DocumentPurpose.GENERATED_CONTRACT, version=version, file=output_file)
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
            "state": state.upper(),
            "source": "commandcore-contract-builder",
            "generation_engine": GENERATION_ENGINE,
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
            "insurance_version": insurance_version,
            "insurance_clause_changes": list(insurance_changes),
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
                "engine": GENERATION_ENGINE,
                "immutable_version": version,
            },
        }
    )
    activity = {
        "activity_type": "contract_generated",
        "title": "Contract generated for review",
        "summary": f"{contract_type} v{version} generated from approved template version {template.get('version')} using {insurance_version} language.",
        "source": "commandcore-contract-builder",
        "details": {
            "generated_document_version": version,
            "template_document_id": template_id,
            "template_version": template.get("version"),
            "facts_document_id": _text(facts_document.get("id")) or None,
            "insurance_version": insurance_version,
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
        insurance_version=insurance_version,
    )
