"""Compatibility boundary for the existing V14 CFD Builder property-source contract."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .google_sheet_property_rows import RowNormalizationResult, normalize_google_sheet_row


class V14PropertySourceType(StrEnum):
    DIRECT_GOOGLE_SHEET = "Direct Google Sheet"
    DRIVE_XLSX = "Google Drive XLSX"


class V14PropertySourceContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    source_type: V14PropertySourceType
    source_reference: str
    tab_name: str


_COMPLETE_ADDRESS = re.compile(
    r"^\s*(?P<address>.+?)\s*,\s*(?P<city>[^,]+?)\s*,\s*"
    r"(?P<state>[A-Za-z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)\s*$"
)


def _value(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _text(value: object) -> str:
    cleaned = _value(value)
    return str(cleaned).strip() if cleaned is not None else ""


def _address_parts(row: Mapping[str, Any]) -> dict[str, object | None]:
    complete = _text(row.get("property_address"))
    direct = {
        "address": _value(row.get("address") or row.get("street_address")),
        "city": _value(row.get("city")),
        "state": _value(row.get("state")),
        "zip_code": _value(row.get("zip_code") or row.get("zip")),
    }
    if all(direct.values()):
        return direct
    match = _COMPLETE_ADDRESS.fullmatch(complete)
    if not match:
        return {"address": complete or None, "city": None, "state": None, "zip_code": None}
    return {
        "address": match.group("address"),
        "city": match.group("city"),
        "state": match.group("state").upper(),
        "zip_code": match.group("zip"),
    }


def _stable_property_source_id(parts: Mapping[str, object | None]) -> str | None:
    if not all(parts.values()):
        return None
    identity = "|".join(re.sub(r"[^a-z0-9]+", "", _text(parts[key]).casefold()) for key in ("address", "city", "state", "zip_code"))
    return "property-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _source_reference_hash(context: V14PropertySourceContext) -> str:
    return hashlib.sha256(context.source_reference.encode("utf-8")).hexdigest()[:12]


def adapt_v14_property_row(
    row: Mapping[str, Any],
    *,
    context: V14PropertySourceContext,
    sheet_row_number: int | None = None,
) -> RowNormalizationResult:
    """Adapt a parsed V14 row without authenticating, loading, or writing Google data."""
    if not isinstance(row, Mapping):
        raise TypeError("V14 property row must be a mapping")
    parts = _address_parts(row)
    stable_id = _stable_property_source_id(parts)
    mapped = {
        **parts,
        "source_record_id": stable_id,
        "source_type": context.source_type.value,
        "source_tab": context.tab_name,
        "source_reference_hash": _source_reference_hash(context),
        "source_updated_at": _value(row.get("last_update")),
        "availability": _value(row.get("availability") or row.get("status")) or "Coming Soon",
        "source_row_number": sheet_row_number or _value(row.get("sheet_row")),
        "lockbox_code": _value(row.get("lockbox_code")),
        "bedrooms": _value(row.get("beds")),
        "bathrooms": _value(row.get("baths")),
        "square_feet": _value(row.get("square_feet")),
        "down_payment": _value(row.get("down_payment")),
        "monthly_payment": _value(row.get("total_monthly_payment")),
        "total_price": _value(row.get("sales_price")),
        "interest_rate": _value(row.get("interest_rate")),
        "monthly_principal_interest": _value(row.get("monthly_principal_interest")),
        "monthly_insurance": _value(row.get("monthly_insurance")),
        "monthly_taxes": _value(row.get("monthly_taxes")),
        "insurance_included": _value(row.get("insurance_included")),
        "photo_link": _value(row.get("photo_link")),
        "legal_description": _value(row.get("legal_description")),
        "parcel_number": _value(row.get("parcel_number")),
        "last_tax_bill": _value(row.get("last_tax_bill")),
        "fair_cash_value": _value(row.get("fair_cash_value")),
        "assessed_value": _value(row.get("assessed_value")),
        "lender": _value(row.get("lender")),
        "payment_system": _value(row.get("payment_system")),
        "seller_entity": _value(row.get("seller_entity")),
        "seller_address": _value(row.get("seller_address")),
        "seller_state": _value(row.get("seller_state")),
        "seller_email": _value(row.get("seller_email")),
        "notes": _value(row.get("notes")),
        "date_added": _value(row.get("date_added")),
    }
    return normalize_google_sheet_row(mapped, source_label="CFD Builder Property Inventory")


def adapt_v14_property_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    context: V14PropertySourceContext,
) -> tuple[RowNormalizationResult, ...]:
    return tuple(
        adapt_v14_property_row(row, context=context, sheet_row_number=index)
        for index, row in enumerate(rows, start=1)
    )
