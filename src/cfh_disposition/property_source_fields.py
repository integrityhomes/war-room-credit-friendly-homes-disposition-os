"""Ephemeral, field-level evidence from existing worksheet cells; no persistence."""

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

ALIASES = {
    "owner": "seller_entity", "seller": "seller_entity", "property owner": "seller_entity",
    "owner seller": "seller_entity", "marketing client": "marketing_client", "owner name": "seller_entity",
    "llc trust name": "seller_entity", "llc name": "seller_entity",
    "llc trust address": "seller_address", "llc address": "seller_address",
    "llc trust state": "seller_state", "llc state": "seller_state", "email address": "seller_email",
    "asking price": "sales_price", "sale price": "sales_price", "purchase price": "purchase_price",
    "street": "address", "street address": "address", "city": "city", "state": "state", "zip": "zip", "zip code": "zip",
    "monthly insurance": "monthly_insurance", "insurance amount": "monthly_insurance",
    "monthly tax": "monthly_taxes", "monthlytaxes": "monthly_taxes", "taxes": "taxes_unspecified_period",
    "previous tax amount": "previous_tax_amount", "2023 taxes": "taxes_2023",
    "last tax bill": "last_tax_bill", "fair cash value": "fair_cash_value", "assessed value": "assessed_value",
    "lender": "lender", "payments": "payment_system", "financing terms": "financing_terms",
    "interest": "interest_rate", "interest rate apr": "interest_rate",
    "square footage": "square_feet", "sqft": "square_feet", "apn": "parcel_number", "parcel apn": "parcel_number",
    "note": "additional_note", "property details": "property_details", "availability": "source_status", "status": "source_status",
    "new update date": "update_date", "update date": "update_date", "marketing start date": "marketing_start_date",
    "mortgage date": "mortgage_date", "lien date": "lien_date", "lien county": "lien_county",
    "location mortgage recorded": "mortgage_recorded_location",
}
TEXT_HEADERS = {"added by", "added updated by", "updated by", "marketed by", "fb post", "fb page post", "ig post",
                "website listing", "linkedin", "yt", "tiktok", "bot live", "show on dwelyx", "notify team member",
                "notiffy team member", "acknowledged by", "applied date"}
ALIASES.update({key: key.replace(" ", "_") for key in TEXT_HEADERS})
NUMBERS = {"beds", "baths", "square_feet", "sales_price", "purchase_price", "down_payment", "total_monthly_payment",
           "interest_rate", "monthly_principal_interest", "monthly_insurance", "monthly_taxes", "last_tax_bill",
           "fair_cash_value", "assessed_value", "previous_tax_amount", "taxes_2023"}


def read_source_fields(headers, values, *, address_column=0):
    """Keep every cell, including unknown columns; never silently choose duplicates.

    Access cells and labelled access notes are redacted in evidence. The original
    reader retains the lockbox through its existing restricted field path.
    """
    from .google_property_full_audit import _normalize_source_date
    from .property_change_attention import public_evidence
    from .property_sync_preview import HEADER_FIELDS, explicit_numeric_units, header_key, text

    mapping = {**HEADER_FIELDS, **ALIASES}
    keys = [mapping.get(header_key(h), "") for h in headers]
    counts = Counter(key for key in keys if key)
    codes = tuple(text(values[i]) for i, key in enumerate(keys) if key == "lockbox_code" and i < len(values) and text(values[i]))
    evidence = []
    for i in range(max(len(headers), len(values))):
        header = text(headers[i]) if i < len(headers) else ""
        raw = text(values[i]) if i < len(values) else ""
        key = keys[i] if i < len(keys) else ""
        if i == address_column and not key:
            key = "property_address"
        if not header and not raw:
            continue
        review = "" if key else "Unlabelled field" if not header else "Unrecognized field meaning; raw value retained"
        normalized = raw or None
        if key == "lockbox_code":
            normalized = "[protected]" if raw else None
        elif key == "monthly_insurance" and re.fullmatch(
            r"buyer\s+(?:(?:must|to)\s+)?(?:(?:get|gets|obtain)\s+(?:their\s+)?own\s+insurance|(?:is\s+)?responsible(?:\s+for\s+insurance)?|responsibility)", raw, re.I):
            normalized = {"responsibility": "buyer", "amount": None}
        elif key in NUMBERS:
            if raw.casefold() in {"", "n/a", "na", "not applicable", "not-applicable"}:
                normalized = None
            else:
                amount = str(explicit_numeric_units(key, raw)).replace("$", "").replace(",", "").strip()
                if key == "interest_rate":
                    amount = amount.removesuffix("%")
                try:
                    number = Decimal(amount)
                    if not number.is_finite() or number < 0 or (key in {"beds", "square_feet"} and number != number.to_integral_value()):
                        raise InvalidOperation
                    normalized = str(number)
                except InvalidOperation:
                    normalized, review = None, "Amount or detail is ambiguous; preserve source wording"
        elif key == "insurance_included" and raw:
            normalized = {"yes": True, "y": True, "true": True, "no": False, "n": False, "false": False}.get(raw.casefold())
            if normalized is None:
                review = "Insurance inclusion is unclear"
        elif key in {"update_date", "marketing_start_date", "mortgage_date", "lien_date"} and raw:
            normalized, issue = _normalize_source_date(raw)
            review = "Explicit date cannot be interpreted" if issue else ""
        elif key == "last_update" and raw:
            date_value, issue = _normalize_source_date(raw)
            normalized = raw if issue else date_value  # A name stays text, never an invented date.
        if key and counts[key] > 1:
            normalized, review = None, "Repeated field header; verify which cell applies"
        safe_raw = "[protected]" if key == "lockbox_code" and raw else public_evidence(raw, codes)
        evidence.append({"column": i + 1, "header": public_evidence(header, codes), "field": key or "unmapped",
                         "raw": safe_raw, "normalized": public_evidence(normalized, codes), "review": review})
    return tuple(evidence)
