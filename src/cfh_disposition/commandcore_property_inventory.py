from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict

from .commandcore_secretary import PropertyAvailability, VerifiedPropertyFacts
from .google_sheet_property_rows import (
    CanonicalAvailability,
    NormalizedPropertyRow,
    RowNormalizationResult,
    RowValidationState,
)

PROPERTY_ID_NAMESPACE = UUID("756278c3-f34d-47a6-8acc-930f987d83b6")
PROTECTED_FACT_FIELDS = (
    "address",
    "city",
    "state",
    "zip_code",
    "availability",
    "total_price",
    "down_payment",
    "monthly_payment",
    "interest_rate",
    "financing_type",
    "bedrooms",
    "bathrooms",
    "condition_summary",
)


class SyncResultState(StrEnum):
    NEW_PROPERTY = "New Property"
    UPDATED = "Updated"
    NO_CHANGE = "No Change"
    NEEDS_REVIEW = "Needs Review"
    INVALID_SOURCE_ROW = "Invalid Source Row"
    DUPLICATE = "Duplicate"
    MISSING_REQUIRED_INFORMATION = "Missing Required Information"


class InventoryValidationState(StrEnum):
    VERIFIED = "Verified"
    NEEDS_REVIEW = "Needs Review"
    INVALID = "Invalid"
    STALE = "Stale"


class FieldProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    field_name: str
    source_label: str
    source_record_id: str
    source_row_hash: str
    source_updated_at: str | None = None
    source_type: str = ""
    source_tab: str = ""
    source_reference_hash: str = ""
    commandcore_synced_at: datetime


class InventoryConflict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str
    existing_value: str
    proposed_value: str
    existing_source: str
    proposed_source: str
    reason: str


class CanonicalPropertyRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    commandcore_property_id: str
    source_label: str
    source_record_id: str
    source_row_hash: str
    source_updated_at: str | None = None
    source_type: str = ""
    source_tab: str = ""
    source_reference_hash: str = ""
    address: str
    city: str
    state: str
    zip_code: str
    county: str = ""
    availability: CanonicalAvailability
    detailed_internal_status: str
    property_type: str = ""
    bedrooms: int | None = None
    bathrooms: Decimal | None = None
    square_feet: int | None = None
    asking_or_sale_price: Decimal | None = None
    down_payment: Decimal | None = None
    monthly_payment: Decimal | None = None
    interest_rate: Decimal | None = None
    term_months: int | None = None
    financing_type: str = ""
    condition_or_repair_notes: str = ""
    assigned_worker_or_team: str = ""
    market: str = ""
    campaign: str = ""
    source_row_number: int | None = None
    lockbox_code: str = ""
    monthly_principal_interest: Decimal | None = None
    monthly_insurance: Decimal | None = None
    monthly_taxes: Decimal | None = None
    insurance_included: str = ""
    photo_link: str = ""
    legal_description: str = ""
    parcel_number: str = ""
    last_tax_bill: Decimal | None = None
    fair_cash_value: Decimal | None = None
    assessed_value: Decimal | None = None
    lender: str = ""
    payment_system: str = ""
    seller_entity: str = ""
    seller_address: str = ""
    seller_state: str = ""
    seller_email: str = ""
    notes: str = ""
    date_added: str = ""
    public_marketing_eligible: bool = False
    last_commandcore_sync: datetime
    validation_state: InventoryValidationState
    source_of_truth: bool
    provenance: tuple[FieldProvenance, ...]
    unresolved_conflicts: tuple[InventoryConflict, ...] = ()
    external_action_started: bool = False


class PropertySyncResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: SyncResultState
    source_record_id: str | None = None
    commandcore_property_id: str | None = None
    record: CanonicalPropertyRecord | None = None
    conflicts: tuple[InventoryConflict, ...] = ()
    reasons: tuple[str, ...] = ()
    marketing_review_required: bool = False
    campaign_shutdown_started: bool = False
    records_written: int = 0
    external_action_started: bool = False


class SecretaryInventoryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: VerifiedPropertyFacts | None = None
    needs_confirmation: bool
    reason: str
    source_is_ai_memory: bool = False


class MarketingInventoryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    property_id: str
    eligible_for_new_marketing: bool
    review_active_marketing: bool
    shutdown_recommended: bool
    reason: str
    campaign_action_started: bool = False
    external_action_started: bool = False


def _identity_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def address_fingerprint(row: NormalizedPropertyRow | CanonicalPropertyRecord) -> str:
    return ":".join(_identity_text(str(getattr(row, field))) for field in ("address", "city", "state", "zip_code"))


def deterministic_property_id(source_label: str, source_record_id: str) -> str:
    source_key = f"{source_label.strip().casefold()}:{source_record_id.strip().casefold()}"
    if not source_label.strip() or not source_record_id.strip():
        raise ValueError("Stable source identity is required")
    return str(uuid5(PROPERTY_ID_NAMESPACE, source_key))


def _source_key(item: NormalizedPropertyRow | CanonicalPropertyRecord) -> tuple[str, str]:
    return item.source_label.casefold(), item.source_record_id.casefold()


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _publicly_marketable(availability: CanonicalAvailability) -> bool:
    return availability is CanonicalAvailability.AVAILABLE


def _detailed_status(availability: CanonicalAvailability) -> str:
    return {
        CanonicalAvailability.AVAILABLE: "Ready to Launch",
        CanonicalAvailability.PENDING: "Pending",
        CanonicalAvailability.SOLD_UNAVAILABLE: "Sold",
        CanonicalAvailability.PAUSED: "Paused",
        CanonicalAvailability.COMING_SOON: "Draft",
    }[availability]


def _value(row: NormalizedPropertyRow, field: str) -> object:
    if field == "asking_or_sale_price":
        return row.total_price
    if field == "condition_or_repair_notes":
        return row.condition_summary or ""
    return getattr(row, field)


def _record_from_row(
    row: NormalizedPropertyRow,
    *,
    property_id: str,
    synced_at: datetime,
    existing: CanonicalPropertyRecord | None = None,
    conflicts: Sequence[InventoryConflict] = (),
) -> CanonicalPropertyRecord:
    fields = (
        "address",
        "city",
        "state",
        "zip_code",
        "county",
        "property_type",
        "bedrooms",
        "bathrooms",
        "square_feet",
        "total_price",
        "down_payment",
        "monthly_payment",
        "interest_rate",
        "term_months",
        "financing_type",
        "condition_summary",
        "assigned_worker_or_team",
        "market",
        "campaign",
        "availability",
        "source_row_number",
        "lockbox_code",
        "monthly_principal_interest",
        "monthly_insurance",
        "monthly_taxes",
        "insurance_included",
        "photo_link",
        "legal_description",
        "parcel_number",
        "last_tax_bill",
        "fair_cash_value",
        "assessed_value",
        "lender",
        "payment_system",
        "seller_entity",
        "seller_address",
        "seller_state",
        "seller_email",
        "notes",
        "date_added",
    )
    existing_provenance = {
        item.field_name: item for item in (existing.provenance if existing else ())
    }
    supplied_provenance = {
        field: FieldProvenance(
            field_name=field,
            source_label=row.source_label,
            source_record_id=row.source_record_id,
            source_row_hash=row.source_row_hash,
            source_updated_at=row.source_updated_at,
            source_type=row.source_type or "",
            source_tab=row.source_tab or "",
            source_reference_hash=row.source_reference_hash or "",
            commandcore_synced_at=synced_at,
        )
        for field in fields
        if getattr(row, field) not in {None, ""}
    }
    provenance = tuple(
        {**existing_provenance, **supplied_provenance}[field]
        for field in sorted({*existing_provenance, *supplied_provenance})
    )

    def supplied_or_existing(row_field: str, record_field: str) -> object:
        value = getattr(row, row_field)
        if value not in {None, ""} or existing is None:
            return value
        return getattr(existing, record_field)

    return CanonicalPropertyRecord(
        commandcore_property_id=property_id,
        source_label=row.source_label,
        source_record_id=row.source_record_id,
        source_row_hash=row.source_row_hash,
        source_updated_at=row.source_updated_at,
        source_type=row.source_type or "",
        source_tab=row.source_tab or "",
        source_reference_hash=row.source_reference_hash or "",
        address=row.address,
        city=row.city,
        state=row.state,
        zip_code=row.zip_code,
        county=supplied_or_existing("county", "county") or "",
        availability=row.availability,
        detailed_internal_status=(
            existing.detailed_internal_status
            if existing and existing.availability is row.availability
            else _detailed_status(row.availability)
        ),
        property_type=supplied_or_existing("property_type", "property_type") or "",
        bedrooms=supplied_or_existing("bedrooms", "bedrooms"),
        bathrooms=supplied_or_existing("bathrooms", "bathrooms"),
        square_feet=supplied_or_existing("square_feet", "square_feet"),
        asking_or_sale_price=supplied_or_existing("total_price", "asking_or_sale_price"),
        down_payment=supplied_or_existing("down_payment", "down_payment"),
        monthly_payment=supplied_or_existing("monthly_payment", "monthly_payment"),
        interest_rate=supplied_or_existing("interest_rate", "interest_rate"),
        term_months=supplied_or_existing("term_months", "term_months"),
        financing_type=supplied_or_existing("financing_type", "financing_type") or "",
        condition_or_repair_notes=(
            supplied_or_existing("condition_summary", "condition_or_repair_notes") or ""
        ),
        assigned_worker_or_team=(
            supplied_or_existing("assigned_worker_or_team", "assigned_worker_or_team") or ""
        ),
        market=supplied_or_existing("market", "market") or "",
        campaign=supplied_or_existing("campaign", "campaign") or "",
        source_row_number=supplied_or_existing("source_row_number", "source_row_number"),
        lockbox_code=supplied_or_existing("lockbox_code", "lockbox_code") or "",
        monthly_principal_interest=supplied_or_existing(
            "monthly_principal_interest", "monthly_principal_interest"
        ),
        monthly_insurance=supplied_or_existing("monthly_insurance", "monthly_insurance"),
        monthly_taxes=supplied_or_existing("monthly_taxes", "monthly_taxes"),
        insurance_included=supplied_or_existing("insurance_included", "insurance_included") or "",
        photo_link=supplied_or_existing("photo_link", "photo_link") or "",
        legal_description=supplied_or_existing("legal_description", "legal_description") or "",
        parcel_number=supplied_or_existing("parcel_number", "parcel_number") or "",
        last_tax_bill=supplied_or_existing("last_tax_bill", "last_tax_bill"),
        fair_cash_value=supplied_or_existing("fair_cash_value", "fair_cash_value"),
        assessed_value=supplied_or_existing("assessed_value", "assessed_value"),
        lender=supplied_or_existing("lender", "lender") or "",
        payment_system=supplied_or_existing("payment_system", "payment_system") or "",
        seller_entity=supplied_or_existing("seller_entity", "seller_entity") or "",
        seller_address=supplied_or_existing("seller_address", "seller_address") or "",
        seller_state=supplied_or_existing("seller_state", "seller_state") or "",
        seller_email=supplied_or_existing("seller_email", "seller_email") or "",
        notes=supplied_or_existing("notes", "notes") or "",
        date_added=supplied_or_existing("date_added", "date_added") or "",
        public_marketing_eligible=_publicly_marketable(row.availability) and not conflicts,
        last_commandcore_sync=synced_at,
        validation_state=InventoryValidationState.NEEDS_REVIEW if conflicts else InventoryValidationState.VERIFIED,
        source_of_truth=not conflicts,
        provenance=provenance,
        unresolved_conflicts=tuple(conflicts),
    )


def _conflicts(existing: CanonicalPropertyRecord, row: NormalizedPropertyRow) -> tuple[InventoryConflict, ...]:
    if _source_key(existing) == _source_key(row):
        return ()
    results: list[InventoryConflict] = []
    for field in PROTECTED_FACT_FIELDS:
        existing_value = getattr(existing, "asking_or_sale_price" if field == "total_price" else "condition_or_repair_notes" if field == "condition_summary" else field)
        proposed_value = _value(row, field)
        if proposed_value not in {None, ""} and existing_value not in {None, ""} and proposed_value != existing_value:
            results.append(
                InventoryConflict(
                    field_name=field,
                    existing_value=str(existing_value),
                    proposed_value=str(proposed_value),
                    existing_source=f"{existing.source_label} / {existing.source_record_id}",
                    proposed_source=f"{row.source_label} / {row.source_record_id}",
                    reason="A different source disagrees with a verified CommandCore property fact.",
                )
            )
    return tuple(results)


def plan_property_sync(
    normalized: RowNormalizationResult,
    existing_records: Sequence[CanonicalPropertyRecord],
    *,
    synced_at: datetime | None = None,
) -> PropertySyncResult:
    if normalized.state is RowValidationState.MISSING_REQUIRED_INFORMATION:
        return PropertySyncResult(state=SyncResultState.MISSING_REQUIRED_INFORMATION, source_record_id=normalized.source_record_id, reasons=normalized.errors)
    if normalized.state is RowValidationState.INVALID_SOURCE_ROW or normalized.normalized is None:
        return PropertySyncResult(state=SyncResultState.INVALID_SOURCE_ROW, source_record_id=normalized.source_record_id, reasons=normalized.errors)
    row = normalized.normalized
    now = synced_at or datetime.now(UTC)
    commandcore_matches = [item for item in existing_records if row.commandcore_property_id and item.commandcore_property_id == row.commandcore_property_id]
    source_matches = [item for item in existing_records if _source_key(item) == _source_key(row)]
    address_matches = [item for item in existing_records if address_fingerprint(item) == address_fingerprint(row)]
    candidates = commandcore_matches or source_matches or address_matches
    unique = {item.commandcore_property_id: item for item in candidates}
    if len(unique) > 1:
        return PropertySyncResult(
            state=SyncResultState.NEEDS_REVIEW,
            source_record_id=row.source_record_id,
            reasons=("More than one CommandCore property matches this source identity or address.",),
        )
    if not unique:
        property_id = row.commandcore_property_id or deterministic_property_id(row.source_label, row.source_record_id)
        record = _record_from_row(row, property_id=property_id, synced_at=now)
        return PropertySyncResult(
            state=SyncResultState.NEW_PROPERTY,
            source_record_id=row.source_record_id,
            commandcore_property_id=property_id,
            record=record,
            marketing_review_required=not record.public_marketing_eligible,
        )
    existing = next(iter(unique.values()))
    if commandcore_matches and address_fingerprint(existing) != address_fingerprint(row):
        conflict = InventoryConflict(
            field_name="property_identity",
            existing_value=address_fingerprint(existing),
            proposed_value=address_fingerprint(row),
            existing_source=f"{existing.source_label} / {existing.source_record_id}",
            proposed_source=f"{row.source_label} / {row.source_record_id}",
            reason="The supplied CommandCore property ID points to a different address.",
        )
        return PropertySyncResult(
            state=SyncResultState.NEEDS_REVIEW,
            source_record_id=row.source_record_id,
            commandcore_property_id=existing.commandcore_property_id,
            conflicts=(conflict,),
            reasons=(conflict.reason,),
            marketing_review_required=True,
        )
    source_time = _timestamp(row.source_updated_at)
    existing_time = _timestamp(existing.source_updated_at)
    if source_time and existing_time and source_time < existing_time:
        return PropertySyncResult(
            state=SyncResultState.NEEDS_REVIEW,
            source_record_id=row.source_record_id,
            commandcore_property_id=existing.commandcore_property_id,
            reasons=("The source row is older than the current verified CommandCore record.",),
            marketing_review_required=True,
        )
    conflicts = _conflicts(existing, row)
    if conflicts:
        proposed = _record_from_row(
            row,
            property_id=existing.commandcore_property_id,
            synced_at=now,
            existing=existing,
            conflicts=conflicts,
        )
        return PropertySyncResult(
            state=SyncResultState.NEEDS_REVIEW,
            source_record_id=row.source_record_id,
            commandcore_property_id=existing.commandcore_property_id,
            record=proposed,
            conflicts=conflicts,
            reasons=tuple(item.reason for item in conflicts),
            marketing_review_required=True,
        )
    proposed = _record_from_row(
        row,
        property_id=existing.commandcore_property_id,
        synced_at=now,
        existing=existing,
    )
    comparable_existing = existing.model_dump(exclude={"last_commandcore_sync", "provenance"})
    comparable_proposed = proposed.model_dump(exclude={"last_commandcore_sync", "provenance"})
    state = SyncResultState.NO_CHANGE if comparable_existing == comparable_proposed else SyncResultState.UPDATED
    restrictive_change = existing.availability is CanonicalAvailability.AVAILABLE and row.availability is not CanonicalAvailability.AVAILABLE
    return PropertySyncResult(
        state=state,
        source_record_id=row.source_record_id,
        commandcore_property_id=existing.commandcore_property_id,
        record=existing if state is SyncResultState.NO_CHANGE else proposed,
        marketing_review_required=restrictive_change or not proposed.public_marketing_eligible,
    )


def plan_inventory_sync(
    rows: Sequence[RowNormalizationResult],
    existing_records: Sequence[CanonicalPropertyRecord],
    *,
    synced_at: datetime | None = None,
) -> tuple[PropertySyncResult, ...]:
    valid = [item.normalized for item in rows if item.normalized is not None]
    source_counts = Counter(_source_key(item) for item in valid)
    address_counts = Counter(address_fingerprint(item) for item in valid)
    results: list[PropertySyncResult] = []
    for item in rows:
        row = item.normalized
        if row and (source_counts[_source_key(row)] > 1 or address_counts[address_fingerprint(row)] > 1):
            results.append(
                PropertySyncResult(
                    state=SyncResultState.DUPLICATE,
                    source_record_id=row.source_record_id,
                    reasons=("The same source identity or property address appears more than once in this batch.",),
                )
            )
        else:
            results.append(plan_property_sync(item, existing_records, synced_at=synced_at))
    return tuple(results)


def secretary_inventory_result(
    record: CanonicalPropertyRecord | None,
    *,
    now: datetime | None = None,
    maximum_age: timedelta = timedelta(days=1),
) -> SecretaryInventoryResult:
    if record is None:
        return SecretaryInventoryResult(needs_confirmation=True, reason="Current CommandCore inventory is unavailable; ask the assigned worker to confirm.")
    current = now or datetime.now(UTC)
    if record.validation_state is not InventoryValidationState.VERIFIED or not record.source_of_truth or record.unresolved_conflicts:
        return SecretaryInventoryResult(needs_confirmation=True, reason="Property information is incomplete or conflicting and needs human confirmation.")
    if current - record.last_commandcore_sync > maximum_age:
        return SecretaryInventoryResult(needs_confirmation=True, reason="Property inventory is stale and must be refreshed before answering.")
    availability = PropertyAvailability(record.availability.value)
    facts = VerifiedPropertyFacts(
        property_id=record.commandcore_property_id,
        availability=availability,
        verified_at=record.last_commandcore_sync,
        source_record_version=record.source_row_hash,
        facts_verified=True,
        address=f"{record.address}, {record.city}, {record.state} {record.zip_code}",
        price=str(record.asking_or_sale_price or ""),
        down_payment=str(record.down_payment or ""),
        monthly_payment=str(record.monthly_payment or ""),
        financing_terms="; ".join(part for part in (record.financing_type, str(record.interest_rate or ""), str(record.term_months or "")) if part),
        condition=record.condition_or_repair_notes,
    )
    return SecretaryInventoryResult(facts=facts, needs_confirmation=False, reason="Verified current CommandCore inventory facts are available.")


def marketing_inventory_result(record: CanonicalPropertyRecord) -> MarketingInventoryResult:
    eligible = (
        record.public_marketing_eligible
        and record.availability is CanonicalAvailability.AVAILABLE
        and record.validation_state is InventoryValidationState.VERIFIED
        and record.source_of_truth
        and not record.unresolved_conflicts
    )
    restrictive = record.availability in {
        CanonicalAvailability.PENDING,
        CanonicalAvailability.SOLD_UNAVAILABLE,
        CanonicalAvailability.PAUSED,
    }
    return MarketingInventoryResult(
        property_id=record.commandcore_property_id,
        eligible_for_new_marketing=eligible,
        review_active_marketing=not eligible,
        shutdown_recommended=restrictive,
        reason=(
            "Property is verified and currently eligible for new marketing."
            if eligible
            else "Property is not eligible for new marketing; review existing packages and campaigns without starting a live action."
        ),
    )


def source_record_ids(records: Iterable[CanonicalPropertyRecord]) -> tuple[str, ...]:
    return tuple(record.source_record_id for record in records)
