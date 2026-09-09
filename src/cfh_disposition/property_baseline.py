"""Prepare a property-only baseline for the existing CRM. Import is hard-disabled."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .commandcore_property_inventory import deterministic_property_id
from .google_sheet_property_rows import normalize_google_sheet_row
from .property_sync_preview import (
    FIELD_ALIASES,
    INVENTORY_TABS,
    NEW,
    REGIONAL_TABS,
    REVIEW,
    SheetProperty,
    address_key,
    address_label,
    compare_properties,
    read_canonical_records,
    regional_sheet_properties,
    text,
)


@dataclass(frozen=True)
class BaselineExpectation:
    properties: int = 155
    active: int = 29
    sold: int = 126
    review: int = 300


VALIDATED_BASELINE = BaselineExpectation()


@dataclass(frozen=True)
class BaselineProperty:
    address: str
    tab: str
    identity_method: str
    record_json: str

    @property
    def record(self) -> dict[str, Any]:
        # A caller cannot mutate the frozen preview through a returned dictionary.
        return json.loads(self.record_json)


@dataclass(frozen=True)
class BaselinePlan:
    properties: tuple[BaselineProperty, ...]
    skipped_review: int
    duplicates_prevented: int
    errors: tuple[str, ...]
    snapshot_hash: str
    observed_at: str
    deletions: int = 0
    updates: int = 0
    deals_created: int = 0
    records_written: int = 0
    import_enabled: bool = False

    @property
    def active_count(self) -> int:
        return sum(item.record["availability"] == "Available" for item in self.properties)

    @property
    def sold_count(self) -> int:
        return sum(item.record["availability"] == "Sold / Unavailable" for item in self.properties)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def build_baseline_plan(
    rows: Sequence[SheetProperty], existing_properties: Sequence[Mapping[str, Any]], *,
    source_reference_hash: str, expectation: BaselineExpectation = VALIDATED_BASELINE, observed_at: str | None = None,
) -> BaselinePlan:
    """Build immutable canonical record proposals, excluding all review/existing rows.

    The baseline totals are a scope check, not authorization. The content hash
    identifies the exact fresh proposal that must be reviewed before future import.
    """
    observed_at = observed_at or datetime.now(UTC).isoformat()
    preview = compare_properties(rows, existing_properties)
    errors = []
    if not source_reference_hash:
        errors.append("Source reference fingerprint is missing.")
    if existing_properties:
        errors.append("Canonical properties are no longer empty. Re-review the baseline; no existing property will be updated.")
    candidates = []
    prevented = 0
    skipped = 0
    seen_addresses: set[str] = set()
    seen_ids: set[str] = set()
    # compare_properties appends unmatched CRM rows after its one result per source row.
    for row, item in zip(rows, preview.items[:len(rows)], strict=True):
        duplicate = any("Duplicate sheet" in reason or "Multiple canonical" in reason for reason in item.review_reasons)
        if duplicate or item.property_id:
            prevented += 1
        if REVIEW in item.categories:
            skipped += 1
            continue
        if NEW not in item.categories or item.property_id:
            continue
        required_status = "Available" if row.tab in REGIONAL_TABS else "Sold / Unavailable" if row.tab == "SOLD" else None
        if required_status is None or row.fields.get("availability") != required_status:
            errors.append(f"{row.tab}, row {row.row}: classification is outside the validated active/sold baseline.")
            continue
        supplied = dict(row.fields)
        supplied["total_price"] = supplied.pop("asking_or_sale_price", None)
        validation = normalize_google_sheet_row(supplied, source_label=text(supplied.get("source_label")))
        if validation.normalized is None:
            errors.append(f"{row.tab}, row {row.row}: property facts failed baseline validation.")
            continue
        facts = validation.normalized.model_dump(mode="json")
        key = address_key(facts)
        method = "External source ID" if row.external_id else "Normalized full address"
        identity = f"external:{row.external_id}" if row.external_id else f"address:{key}"
        property_id = deterministic_property_id(f"cfh-google-sheet:{source_reference_hash}", identity)
        if not key or key in seen_addresses or property_id in seen_ids or any(text(prop.get("id")) == property_id for prop in existing_properties):
            prevented += 1
            errors.append(f"{row.tab}, row {row.row}: duplicate or incomplete identity prevented.")
            continue
        seen_addresses.add(key)
        seen_ids.add(property_id)
        property_facts = {field: facts.get(field) for field in FIELD_ALIASES}
        property_facts["asking_or_sale_price"] = facts.get("total_price")
        property_facts.update({"address": facts["address"], "city": facts["city"], "state": facts["state"], "zip": facts["zip_code"]})
        record = {
            **property_facts, "id": property_id, "entity_type": "properties", "source": "cfh-google-sheet",
            "external_id": row.external_id or None, "source_record_id": facts["source_record_id"],
            "source_updated_at": facts.get("source_updated_at"), "links": {},
            "sync_metadata": {
                "source_reference_hash": source_reference_hash, "source_tab": row.tab, "source_row": row.row,
                "identity_method": method, "normalized_address": key, "source_row_hash": row.fields.get("source_row_hash"),
                "normalized_facts_hash": _hash(property_facts), "observed_at": observed_at,
                "classification_basis": "source worksheet membership", "closing_verified": False,
            },
        }
        candidates.append(BaselineProperty(address_label(facts), row.tab, method, _json(record)))
    active = sum(item.record["availability"] == "Available" for item in candidates)
    sold = sum(item.record["availability"] == "Sold / Unavailable" for item in candidates)
    actual = (len(candidates), active, sold, skipped)
    expected = (expectation.properties, expectation.active, expectation.sold, expectation.review)
    if actual != expected:
        errors.append(f"Baseline scope changed: expected {expected}, observed {actual} (properties, active, sold, review). Inspect the fresh source before proceeding.")
    # Include all proposed facts/identity but exclude observation time and row position:
    # sheet reordering alone does not represent a changed property baseline.
    hashed_records = []
    for item in candidates:
        record = item.record
        record["sync_metadata"].pop("observed_at")
        record["sync_metadata"].pop("source_row")
        record["sync_metadata"].pop("source_row_hash")
        hashed_records.append(record)
    fingerprint = _hash(sorted(hashed_records, key=lambda record: record["id"]))
    return BaselinePlan(tuple(candidates), skipped, prevented, tuple(errors), fingerprint, observed_at)


def import_baseline(*args: Any, **kwargs: Any) -> None:
    """Server-side gate: no approval flag or forced UI event can perform an import."""
    raise PermissionError("Baseline import is disabled. No records were written.")


def load_baseline_source(secrets: Mapping[str, Any]) -> tuple[tuple[SheetProperty, ...], str]:
    """Read the existing validated inventory adapter from one live sheet batch."""
    from google.auth.transport.requests import AuthorizedSession

    from .google_property_readonly_loader import ReadOnlyWorksheetValues, build_read_only_google_credentials
    from .google_property_runtime_bridge import resolve_read_only_google_access

    credentials, sheet_id = resolve_read_only_google_access(secrets, build_read_only_google_credentials)
    names = (*INVENTORY_TABS, "_REIBB_CACHE")
    with AuthorizedSession(credentials) as session:
        response = session.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values:batchGet",
            params=[("ranges", "'" + name.replace("'", "''") + "'") for name in names] + [("valueRenderOption", "FORMATTED_VALUE")], timeout=120,
        )
        response.raise_for_status()
        ranges = response.json().get("valueRanges", [])
    if len(ranges) != len(names):
        raise ValueError("Incomplete inventory batch read")
    worksheets = tuple(ReadOnlyWorksheetValues(name, part.get("values", [])) for name, part in zip(names, ranges, strict=True))
    return regional_sheet_properties(worksheets, sheet_id), hashlib.sha256(sheet_id.encode()).hexdigest()


def load_baseline_preview(secrets: Mapping[str, Any]) -> BaselinePlan:
    from supabase import create_client

    rows, source_reference_hash = load_baseline_source(secrets)
    client = create_client(text(secrets.get("SUPABASE_URL")), text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
    existing = read_canonical_records(client, "properties")
    return build_baseline_plan(rows, existing, source_reference_hash=source_reference_hash)
