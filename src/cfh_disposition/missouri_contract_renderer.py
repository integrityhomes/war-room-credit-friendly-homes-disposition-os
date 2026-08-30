from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta
from docx import Document
from docxtpl import DocxTemplate

from .contract_document_renderer import AMORTIZATION_MARKER, format_currency, insert_amortization_table


def format_percentage(value: float) -> str:
    return f"{value:.4f}%"


def ordinal_day(day_number: int) -> str:
    if 10 <= day_number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day_number % 10, "th")
    return f"{day_number}{suffix}"


def _full_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def _combine(values: list[str], separator: str = " and ") -> str:
    return separator.join(value.strip() for value in values if value.strip())


def _split_address(address: str) -> tuple[str, str]:
    normalized = " ".join(address.split())
    parts = [part.strip() for part in normalized.split(",")]
    if len(parts) >= 3:
        return parts[0], ", ".join(parts[1:])
    return normalized, ""


def extract_city_from_address(address: str) -> str:
    _, city_state_zip = _split_address(address)
    if city_state_zip and "," in city_state_zip:
        return city_state_zip.split(",", 1)[0].strip()
    return "Saint Louis"


def build_missouri_contract_context(
    *,
    property_address: str,
    seller_name: str,
    seller_address: str,
    buyer_1_name: str,
    buyer_2_name: str,
    buyer_1_email: str,
    buyer_2_email: str,
    buyer_1_phone: str,
    buyer_2_phone: str,
    contract_date: date,
    first_payment_date: date,
    sales_price: float,
    down_payment: float,
    amount_financed: float,
    annual_interest_rate: float,
    number_of_payments: int,
    monthly_principal_interest: float,
    monthly_taxes: float,
    monthly_servicing_fee: float,
    total_monthly_payment: float,
    conversion_rent: float,
    payment_payee: str,
    payment_address: str,
    payment_system: str,
    late_fee_percent: float,
    grace_period_days: int,
    apr: float,
    finance_charge: float,
    total_of_payments: float,
    use_primary: bool,
    use_investment: bool,
    use_fix_flip: bool,
    use_family: bool,
    use_short_term: bool,
    use_landlord: bool,
    use_other: bool,
    use_other_text: str,
) -> dict[str, Any]:
    buyer_names = _combine([buyer_1_name, buyer_2_name])
    buyer_emails = _combine([buyer_1_email, buyer_2_email], separator="; ")
    buyer_phones = _combine([buyer_1_phone, buyer_2_phone], separator="; ")
    property_city = extract_city_from_address(property_address)
    final_payment_date = first_payment_date + relativedelta(months=max(number_of_payments - 1, 0))
    loan_years = number_of_payments / 12
    if float(loan_years).is_integer():
        loan_term = f"{number_of_payments} months ({int(loan_years)} years)"
    else:
        loan_term = f"{number_of_payments} months"

    def checked(value: bool) -> str:
        return "[X]" if value else "[ ]"

    return {
        "AMORTIZATION_SCHEDULE": AMORTIZATION_MARKER,
        "AMORTIZATION_START_DATE": _full_date(first_payment_date),
        "AMORTIZATION_END_DATE": _full_date(final_payment_date),
        "AMOUNT_FINANCED": format_currency(amount_financed),
        "APR": format_percentage(apr),
        "BUYER_EMAILS": buyer_emails,
        "BUYER_NAMES": buyer_names,
        "BUYER_PHONES": buyer_phones,
        "CONTRACT_DATE": _full_date(contract_date),
        "CONTRACT_DAY": ordinal_day(contract_date.day),
        "CONTRACT_MONTH_YEAR": contract_date.strftime("%B %Y"),
        "CONVERSION_RENT": format_currency(conversion_rent),
        "DOWN_PAYMENT": format_currency(down_payment),
        "FINAL_PAYMENT_DATE": _full_date(final_payment_date),
        "FINANCE_CHARGE": format_currency(finance_charge),
        "FIRST_PAYMENT_DATE": _full_date(first_payment_date),
        "FIRST_PAYMENT_MONTH_YEAR": first_payment_date.strftime("%B %Y"),
        "GRACE_PERIOD_DAYS": str(grace_period_days),
        "INTEREST_RATE": format_percentage(annual_interest_rate),
        "LATE_FEE_PERCENT": f"{late_fee_percent:g}%",
        "LOAN_TERM": loan_term,
        "MONTHLY_PRINCIPAL_INTEREST": format_currency(monthly_principal_interest),
        "MONTHLY_SERVICING_FEE": format_currency(monthly_servicing_fee),
        "MONTHLY_TAXES": format_currency(monthly_taxes),
        "NUMBER_OF_PAYMENTS": str(number_of_payments),
        "PAYMENT_ADDRESS": payment_address,
        "PAYMENT_PAYEE": payment_payee,
        "PAYMENT_SYSTEM": payment_system,
        "PROPERTY_ADDRESS": property_address,
        "PROPERTY_CITY": property_city,
        "SALES_PRICE": format_currency(sales_price),
        "SELLER_ADDRESS": seller_address,
        "SELLER_NAME": seller_name,
        "TAX_YEAR": str(contract_date.year),
        "TOTAL_MONTHLY_PAYMENT": format_currency(total_monthly_payment),
        "TOTAL_OF_PAYMENTS": format_currency(total_of_payments),
        "USE_PRIMARY": checked(use_primary),
        "USE_INVESTMENT": checked(use_investment),
        "USE_FIX_FLIP": checked(use_fix_flip),
        "USE_FAMILY": checked(use_family),
        "USE_SHORT_TERM": checked(use_short_term),
        "USE_LANDLORD": checked(use_landlord),
        "USE_OTHER": checked(use_other),
        "USE_OTHER_TEXT": use_other_text.strip(),
    }


def generate_missouri_contract_document(
    *,
    template_bytes: bytes,
    context: dict[str, Any],
    amortization_schedule: pd.DataFrame,
) -> bytes:
    if not template_bytes:
        raise ValueError("Approved Missouri Agreement for Deed template bytes are required.")

    template = DocxTemplate(BytesIO(template_bytes))
    template.render(context, autoescape=True)
    rendered_buffer = BytesIO()
    template.save(rendered_buffer)
    rendered_buffer.seek(0)

    document = Document(rendered_buffer)
    insert_amortization_table(document, amortization_schedule)

    completed_buffer = BytesIO()
    document.save(completed_buffer)
    completed_buffer.seek(0)
    return completed_buffer.getvalue()
