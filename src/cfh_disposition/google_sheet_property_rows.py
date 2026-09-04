from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalAvailability(StrEnum):
    AVAILABLE = "Available"
    PENDING = "Pending"
    SOLD_UNAVAILABLE = "Sold / Unavailable"
    PAUSED = "Paused"
    COMING_SOON = "Coming Soon"


class RowValidationState(StrEnum):
    VALID = "Valid"
    INVALID_SOURCE_ROW = "Invalid Source Row"
    MISSING_REQUIRED_INFORMATION = "Missing Required Information"


class NormalizedPropertyRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_label: str
    source_record_id: str
    source_updated_at: str | None = None
    source_row_hash: str
    source_type: str | None = None
    source_tab: str | None = None
    source_reference_hash: str | None = None
    commandcore_property_id: str | None = None
    address: str
    city: str
    state: str
    zip_code: str
    county: str | None = None
    availability: CanonicalAvailability
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: Decimal | None = Field(default=None, ge=0)
    square_feet: int | None = Field(default=None, ge=0)
    total_price: Decimal | None = Field(default=None, ge=0)
    down_payment: Decimal | None = Field(default=None, ge=0)
    monthly_payment: Decimal | None = Field(default=None, ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    term_months: int | None = Field(default=None, ge=1)
    condition_summary: str | None = None
    public_disclosures: str | None = None
    property_type: str | None = None
    financing_type: str | None = None
    assigned_worker_or_team: str | None = None
    market: str | None = None
    campaign: str | None = None
    market_campaign: str | None = None
    source_row_number: int | None = Field(default=None, ge=1)
    lockbox_code: str | None = None
    monthly_principal_interest: Decimal | None = Field(default=None, ge=0)
    monthly_insurance: Decimal | None = Field(default=None, ge=0)
    monthly_taxes: Decimal | None = Field(default=None, ge=0)
    insurance_included: str | None = None
    photo_link: str | None = None
    legal_description: str | None = None
    parcel_number: str | None = None
    last_tax_bill: Decimal | None = Field(default=None, ge=0)
    fair_cash_value: Decimal | None = Field(default=None, ge=0)
    assessed_value: Decimal | None = Field(default=None, ge=0)
    lender: str | None = None
    payment_system: str | None = None
    seller_entity: str | None = None
    seller_address: str | None = None
    seller_state: str | None = None
    seller_email: str | None = None
    notes: str | None = None
    date_added: str | None = None


class RowNormalizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: RowValidationState
    normalized: NormalizedPropertyRow | None = None
    errors: tuple[str, ...] = ()
    source_label: str
    source_record_id: str | None = None
    source_updated_at: str | None = None
    source_row_hash: str


_ALIASES: dict[str, tuple[str, ...]] = {
    "source_record_id": ("source_record_id", "source_id", "record_id", "inventory_id"),
    "source_updated_at": ("source_updated_at", "updated_at", "last_updated", "modified_at"),
    "source_type": ("source_type",),
    "source_tab": ("source_tab", "worksheet_name", "tab_name"),
    "source_reference_hash": ("source_reference_hash",),
    "commandcore_property_id": ("commandcore_property_id", "property_id", "commandcore_id"),
    "address": ("address", "street_address", "property_address", "street"),
    "city": ("city",),
    "state": ("state", "state_code"),
    "zip_code": ("zip_code", "zip", "postal_code"),
    "county": ("county",),
    "availability": ("availability", "status", "property_status"),
    "bedrooms": ("bedrooms", "beds", "bed"),
    "bathrooms": ("bathrooms", "baths", "bath"),
    "square_feet": ("square_feet", "sqft", "square_footage"),
    "total_price": ("total_price", "price", "purchase_price"),
    "down_payment": ("down_payment", "down", "minimum_down_payment"),
    "monthly_payment": ("monthly_payment", "monthly", "payment"),
    "interest_rate": ("interest_rate", "rate"),
    "term_months": ("term_months", "term"),
    "condition_summary": ("condition_summary", "condition"),
    "public_disclosures": ("public_disclosures", "disclosures"),
    "property_type": ("property_type", "home_type", "asset_type"),
    "financing_type": ("financing_type", "finance_type", "financing"),
    "assigned_worker_or_team": (
        "assigned_worker_or_team",
        "assigned_worker",
        "assigned_team",
        "owner_or_team",
    ),
    "market": ("market", "market_name"),
    "campaign": ("campaign", "campaign_name", "campaign_id"),
    "market_campaign": ("market_campaign", "campaign", "market"),
    "source_row_number": ("source_row_number", "sheet_row"),
    "lockbox_code": ("lockbox_code", "lockbox"),
    "monthly_principal_interest": ("monthly_principal_interest", "monthly_pi"),
    "monthly_insurance": ("monthly_insurance", "insurance"),
    "monthly_taxes": ("monthly_taxes", "taxes"),
    "insurance_included": ("insurance_included",),
    "photo_link": ("photo_link", "photos"),
    "legal_description": ("legal_description", "legal"),
    "parcel_number": ("parcel_number", "parcel", "pin"),
    "last_tax_bill": ("last_tax_bill", "annual_taxes"),
    "fair_cash_value": ("fair_cash_value",),
    "assessed_value": ("assessed_value",),
    "lender": ("lender",),
    "payment_system": ("payment_system",),
    "seller_entity": ("seller_entity",),
    "seller_address": ("seller_address",),
    "seller_state": ("seller_state",),
    "seller_email": ("seller_email",),
    "notes": ("notes",),
    "date_added": ("date_added",),
}

_STATUS_ALIASES = {
    "available": CanonicalAvailability.AVAILABLE,
    "ready": CanonicalAvailability.AVAILABLE,
    "ready to launch": CanonicalAvailability.AVAILABLE,
    "marketing live": CanonicalAvailability.AVAILABLE,
    "pending": CanonicalAvailability.PENDING,
    "under contract": CanonicalAvailability.PENDING,
    "sold": CanonicalAvailability.SOLD_UNAVAILABLE,
    "filled": CanonicalAvailability.SOLD_UNAVAILABLE,
    "unavailable": CanonicalAvailability.SOLD_UNAVAILABLE,
    "sold / unavailable": CanonicalAvailability.SOLD_UNAVAILABLE,
    "paused": CanonicalAvailability.PAUSED,
    "hold": CanonicalAvailability.PAUSED,
    "coming soon": CanonicalAvailability.COMING_SOON,
    "draft": CanonicalAvailability.COMING_SOON,
    "needs information": CanonicalAvailability.COMING_SOON,
}


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_row(row: Mapping[str, Any]) -> dict[str, Any]:
    keyed = {_key(key): value for key, value in row.items()}
    return {
        field: next((keyed[name] for name in names if name in keyed), None)
        for field, names in _ALIASES.items()
    }


def _hash_row(row: Mapping[str, Any]) -> str:
    safe = {_key(key): str(value) if value is not None else None for key, value in row.items()}
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decimal(value: object, field: str, errors: list[str]) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").rstrip("%").strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        errors.append(f"{field} must be a number.")
        return None
    if not number.is_finite() or number < 0:
        errors.append(f"{field} must be a non-negative finite number.")
        return None
    return number


def _integer(value: object, field: str, errors: list[str]) -> int | None:
    number = _decimal(value, field, errors)
    if number is None:
        return None
    if number != number.to_integral_value():
        errors.append(f"{field} must be a whole number.")
        return None
    return int(number)


def _valid_source_id(value: str | None) -> bool:
    if not value or len(value) > 200:
        return False
    compact = _key(value)
    if not compact or compact.isdigit():
        return False
    return not re.fullmatch(r"(?:row|line|sheet_row)_?\d+", compact)


def _valid_timestamp(value: str | None) -> bool:
    if value is None:
        return True
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def normalize_google_sheet_row(
    row: Mapping[str, Any], *, source_label: str = "Google Sheet"
) -> RowNormalizationResult:
    """Normalize one mocked row without mutating it or contacting Google."""
    if not isinstance(row, Mapping):
        raise TypeError("row must be a mapping")
    row_hash = _hash_row(row)
    label = _text(source_label) or ""
    raw = _canonical_row(row)
    source_id = _text(raw["source_record_id"])
    updated_at = _text(raw["source_updated_at"])
    missing: list[str] = []
    errors: list[str] = []

    if not label:
        missing.append("Source label is required.")
    if source_id is None:
        missing.append("Stable source record ID is required; a row number is not sufficient.")
    elif not _valid_source_id(source_id):
        errors.append("Source record ID must be stable and must not be a row number.")

    required = {name: _text(raw[name]) for name in ("address", "city", "state", "zip_code")}
    for name, value in required.items():
        if value is None:
            missing.append(f"{name.replace('_', ' ').title()} is required.")
    status_text = _text(raw["availability"])
    if status_text is None:
        missing.append("Availability is required.")
        availability = None
    else:
        availability = _STATUS_ALIASES.get(status_text.casefold())
        if availability is None:
            errors.append("Availability must map to an approved property status.")

    state = (required["state"] or "").upper()
    if state and not re.fullmatch(r"[A-Z]{2}", state):
        errors.append("State must be a two-letter code.")
    zip_code = required["zip_code"] or ""
    if zip_code and not re.fullmatch(r"\d{5}(?:-\d{4})?", zip_code):
        errors.append("ZIP code must be 5 digits or ZIP+4.")
    if not _valid_timestamp(updated_at):
        errors.append("Source updated time must be an ISO-8601 timestamp.")

    values = {
        "bedrooms": _integer(raw["bedrooms"], "Bedrooms", errors),
        "bathrooms": _decimal(raw["bathrooms"], "Bathrooms", errors),
        "square_feet": _integer(raw["square_feet"], "Square feet", errors),
        "total_price": _decimal(raw["total_price"], "Total price", errors),
        "down_payment": _decimal(raw["down_payment"], "Down payment", errors),
        "monthly_payment": _decimal(raw["monthly_payment"], "Monthly payment", errors),
        "interest_rate": _decimal(raw["interest_rate"], "Interest rate", errors),
        "term_months": _integer(raw["term_months"], "Term months", errors),
        "source_row_number": _integer(raw["source_row_number"], "Source row number", errors),
        "monthly_principal_interest": _decimal(raw["monthly_principal_interest"], "Monthly principal and interest", errors),
        "monthly_insurance": _decimal(raw["monthly_insurance"], "Monthly insurance", errors),
        "monthly_taxes": _decimal(raw["monthly_taxes"], "Monthly taxes", errors),
        "last_tax_bill": _decimal(raw["last_tax_bill"], "Last tax bill", errors),
        "fair_cash_value": _decimal(raw["fair_cash_value"], "Fair cash value", errors),
        "assessed_value": _decimal(raw["assessed_value"], "Assessed value", errors),
    }

    result_state = (
        RowValidationState.MISSING_REQUIRED_INFORMATION
        if missing
        else RowValidationState.INVALID_SOURCE_ROW
        if errors
        else RowValidationState.VALID
    )
    all_errors = tuple(missing + errors)
    normalized = None
    if result_state is RowValidationState.VALID:
        normalized = NormalizedPropertyRow(
            source_label=label,
            source_record_id=source_id or "",
            source_updated_at=updated_at,
            source_row_hash=row_hash,
            source_type=_text(raw["source_type"]),
            source_tab=_text(raw["source_tab"]),
            source_reference_hash=_text(raw["source_reference_hash"]),
            commandcore_property_id=_text(raw["commandcore_property_id"]),
            address=required["address"] or "",
            city=required["city"] or "",
            state=state,
            zip_code=zip_code,
            county=_text(raw["county"]),
            availability=availability or CanonicalAvailability.COMING_SOON,
            condition_summary=_text(raw["condition_summary"]),
            public_disclosures=_text(raw["public_disclosures"]),
            property_type=_text(raw["property_type"]),
            financing_type=_text(raw["financing_type"]),
            assigned_worker_or_team=_text(raw["assigned_worker_or_team"]),
            market=_text(raw["market"]),
            campaign=_text(raw["campaign"]),
            market_campaign=_text(raw["market_campaign"]),
            lockbox_code=_text(raw["lockbox_code"]),
            insurance_included=_text(raw["insurance_included"]),
            photo_link=_text(raw["photo_link"]),
            legal_description=_text(raw["legal_description"]),
            parcel_number=_text(raw["parcel_number"]),
            lender=_text(raw["lender"]),
            payment_system=_text(raw["payment_system"]),
            seller_entity=_text(raw["seller_entity"]),
            seller_address=_text(raw["seller_address"]),
            seller_state=_text(raw["seller_state"]),
            seller_email=_text(raw["seller_email"]),
            notes=_text(raw["notes"]),
            date_added=_text(raw["date_added"]),
            **values,
        )
    return RowNormalizationResult(
        state=result_state,
        normalized=normalized,
        errors=all_errors,
        source_label=label,
        source_record_id=source_id,
        source_updated_at=updated_at,
        source_row_hash=row_hash,
    )
