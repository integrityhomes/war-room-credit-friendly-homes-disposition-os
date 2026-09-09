"""Read-only change projection over the existing sheet adapter and canonical CRM.

No persistence or notification transport. Callers own the small hash-only
checkpoint; canonical records remain the only property database.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .property_sync_preview import (
    FIELD_ALIASES,
    MISSING,
    NEW,
    OTHER,
    PRICE,
    REVIEW,
    SOLD,
    STATUS,
    TERMS,
    PreviewItem,
    address_key,
    comparable,
    compare_properties,
)

RETURNED = "PROPERTY RETURNED TO ACTIVE"
SOLD_CHANGE = "SOLD / UNAVAILABLE CHANGE"
CHANGE_TYPES = (NEW, PRICE, TERMS, STATUS, SOLD_CHANGE, RETURNED, OTHER, MISSING)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class DetectionState:
    source_fingerprint: str = ""
    seen_ids: frozenset[str] = frozenset()

    def checkpoint(self) -> dict:
        return {"version": 1, "source_fingerprint": self.source_fingerprint, "seen_ids": sorted(self.seen_ids)}

    @classmethod
    def from_checkpoint(cls, value):
        if value.get("version") != 1 or not isinstance(value.get("seen_ids"), list):
            raise ValueError("Unsupported detection checkpoint")
        return cls(value["source_fingerprint"], frozenset(value["seen_ids"]))


@dataclass(frozen=True)
class PropertyChange:
    event_id: str
    categories: tuple[str, ...]
    evidence: PreviewItem


@dataclass(frozen=True)
class DetectionResult:
    changes: tuple[PropertyChange, ...]
    new_events: tuple[PropertyChange, ...]
    state: DetectionState
    checked_at: str
    review_rows: int
    unchanged: int
    records_written: int = 0
    external_actions_started: int = 0

    @property
    def counts(self):
        return {kind: sum(kind in change.categories for change in self.changes) for kind in CHANGE_TYPES}


def detect_property_changes(rows, properties, *, source_reference: str, previous: DetectionState | None = None) -> DetectionResult:
    if not source_reference:
        raise ValueError("Source identity is required")
    previous = previous or DetectionState()
    preview = compare_properties(rows, properties)
    managed_ids = {prop.get("id") for prop in properties if prop.get("source") == "cfh-google-sheet"
                   and (prop.get("sync_metadata") or {}).get("source_reference_hash") == source_reference}
    changes = []
    for index, item in enumerate(preview.items):
        # Invalid/duplicate rows stay excluded. Unmatched canonical records are
        # review only, including when invalid sheet rows prevent proving absence.
        missing = index >= len(rows) and bool(item.property_id)
        if missing and item.property_id not in managed_ids:
            continue  # Other CRM properties are not required to appear in this sheet.
        if REVIEW in item.categories and not missing:
            continue
        kinds = [SOLD_CHANGE if kind == SOLD else kind for kind in item.categories if kind != REVIEW]
        if missing:
            kinds = [MISSING]
        if any(change.field == "availability" and comparable("availability", change.current) == "sold / unavailable"
               and comparable("availability", change.proposed) == "available" for change in item.changes):
            kinds.append(RETURNED)
        if not kinds:
            continue
        row = rows[index] if index < len(rows) else None
        identity = item.property_id or (row.external_id if row else "") or (address_key(row.fields) if row else "")
        facts = sorted((change.field, comparable(change.field, change.current), comparable(change.field, change.proposed)) for change in item.changes)
        event_id = digest([source_reference, identity, sorted(kinds), facts])
        changes.append(PropertyChange(event_id, tuple(dict.fromkeys(kinds)), item))
    changes.sort(key=lambda change: change.event_id)
    # Exclude row numbers, sheet order, timestamps and numeric presentation.
    source_fingerprint = digest([source_reference, sorted(
        (row.external_id, address_key(row.fields), sorted((key, comparable(key, value)) for key, value in row.fields.items()
         if key in FIELD_ALIASES), sorted(row.issues))
        for row in rows
    )])
    fresh = tuple(change for change in changes if change.event_id not in previous.seen_ids)
    state = DetectionState(source_fingerprint, previous.seen_ids | frozenset(change.event_id for change in changes))
    return DetectionResult(tuple(changes), fresh, state, datetime.now(UTC).isoformat(),
                           sum(REVIEW in item.categories for item in preview.items[:len(rows)]),
                           sum(not item.categories for item in preview.items))


def is_property_change_question(request: str) -> bool:
    text = request.casefold()
    return any(term in text for term in ("properties changed", "new properties", "prices changed", "became sold", "became unavailable", "returned to active"))


def selected_changes(request: str, result: DetectionResult):
    text = request.casefold()
    category = NEW if "new properties" in text else PRICE if "prices" in text else RETURNED if "returned to active" in text else SOLD_CHANGE if "sold" in text or "unavailable" in text else None
    return tuple(change for change in result.changes if category is None or category in change.categories)
