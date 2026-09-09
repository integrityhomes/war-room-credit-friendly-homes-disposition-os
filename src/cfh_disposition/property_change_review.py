"""Exact property patch proposals and local review decisions. Live Apply is disabled."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from .property_baseline import BaselineExpectation, build_baseline_plan, load_baseline_source
from .property_change_cache import cache_path, exclusive_check, read_cache, save_cache
from .property_change_detection import detect_property_changes, digest
from .property_sync_preview import FIELD_ALIASES, MISSING, NEW, NUMERIC_FIELDS, REVIEW, address_key, comparable, first, read_canonical_records, text

SAFE_FIELDS = NUMERIC_FIELDS | {"availability", "insurance_included"}
ABSENT = {"", "n/a", "na", "not applicable", "not-applicable", "none", "null"}


@dataclass(frozen=True)
class ReviewProposal:
    event_id: str
    property_id: str
    patch: dict
    expected_values: dict
    record_fingerprint: str
    errors: tuple[str, ...]
    new_property: dict | None = None
    apply_enabled: bool = False


def proposed_value(field, value):
    raw = text(value)
    if raw.casefold() in ABSENT:
        raise ValueError("Blank or not-applicable source value cannot overwrite a property fact.")
    if field in NUMERIC_FIELDS:
        try:
            number = Decimal(raw.replace("$", "").replace(",", "").rstrip("%"))
        except InvalidOperation:
            raise ValueError("Invalid numeric source value.") from None
        if not number.is_finite() or number < 0 or (field == "interest_rate" and number > 100):
            raise ValueError("Numeric source value is outside the permitted range.")
        if field in {"bedrooms", "square_feet"}:
            if number != number.to_integral_value():
                raise ValueError("Ambiguous whole-number source value.")
            return int(number)
        return str(number)
    if field == "availability" and raw not in {"Available", "Pending", "Sold / Unavailable", "Paused", "Coming Soon"}:
        raise ValueError("Unrecognized source classification.")
    if field == "insurance_included" and raw.casefold() not in {"yes", "no"}:
        raise ValueError("Insurance wording requires investigation.")
    return raw


def prepare_patch(change, record) -> ReviewProposal:
    errors, patch, expected = [], {}, {}
    evidence = change.evidence
    if MISSING in change.categories or REVIEW in change.categories or NEW in change.categories:
        errors.append("This item requires investigation or new-property validation, not an existing-property update.")
    if not record or record.get("id") != evidence.property_id or record.get("archived"):
        errors.append("Existing canonical identity is missing, changed, or archived.")
    for item in evidence.changes:
        if item.field not in SAFE_FIELDS:
            errors.append(f"{item.field}: explicit investigation is required.")
            continue
        aliases = FIELD_ALIASES[item.field]
        current = first(record, aliases)
        if comparable(item.field, current) != comparable(item.field, item.current):
            errors.append(f"{item.field}: canonical value changed since detection.")
            continue
        try:
            value = proposed_value(item.field, item.proposed)
        except ValueError as exc:
            errors.append(f"{item.field}: {exc}")
            continue
        if comparable(item.field, current) == comparable(item.field, value):
            continue
        key = next((key for key in aliases if record.get(key) not in (None, "")), aliases[0])
        patch[key], expected[key] = value, record.get(key)
    return ReviewProposal(change.event_id, evidence.property_id, {} if errors else patch, expected,
                          digest(record), tuple(errors))


def prepare_from_snapshot(event_id, rows, properties, source):
    current = detect_property_changes(rows, properties, source_reference=source)
    change = next((item for item in current.changes if item.event_id == event_id), None)
    if change is None:
        return ReviewProposal(event_id, "", {}, {}, "", ("Change is stale, resolved, invalid, or no longer matches the source. Recheck the queue.",))
    if NEW in change.categories:
        row = next(row for row in rows if row.tab == change.evidence.tab and row.row == change.evidence.row)
        sold = row.fields.get("availability") == "Sold / Unavailable"
        plan = build_baseline_plan([row], [], source_reference_hash=source,
                                   expectation=BaselineExpectation(1, int(not sold), int(sold), 0))
        candidate = plan.properties[0].record if not plan.errors and len(plan.properties) == 1 else None
        if candidate and any(prop.get("id") == candidate["id"] or address_key(prop) == address_key(candidate) for prop in properties):
            candidate = None
        return ReviewProposal(event_id, "", {}, {}, "", plan.errors or (() if candidate else ("New-property validation failed.",)), candidate)
    record = next((prop for prop in properties if prop.get("id") == change.evidence.property_id), {})
    return prepare_patch(change, record)


def read_review_proposal(secrets, event_id):
    from supabase import create_client
    rows, source = load_baseline_source(secrets)
    client = create_client(text(secrets.get("SUPABASE_URL")), text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
    return prepare_from_snapshot(event_id, rows, read_canonical_records(client, "properties"), source)


def record_review_decision(secrets, event_id, decision):
    if decision not in {"Pending", "Ignored", "Needs investigation"}:
        raise ValueError("Unsupported review decision")
    path = cache_path(secrets)
    with exclusive_check(path):
        cached = read_cache(path)
        if event_id not in {item["event_id"] for item in cached.get("result", {}).get("changes", [])}:
            raise ValueError("Change is no longer in the latest queue.")
        if cached.get("review_decisions", {}).get(event_id) == decision:
            return
        cached.setdefault("review_decisions", {})[event_id] = decision
        cached.setdefault("review_history", []).append({"event_id": event_id, "decision": decision, "at": datetime.now(UTC).isoformat()})
        save_cache(path, cached)


def apply_property_update(*args, **kwargs):
    raise PermissionError("Live property Apply is disabled. No records were written.")
