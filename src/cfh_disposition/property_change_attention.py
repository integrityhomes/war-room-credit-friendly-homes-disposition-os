"""Source-to-source attention events inside the existing property detector."""

import hashlib
import hmac
import re
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from .property_change_detection import OTHER, PRICE, RETURNED, SOLD_CHANGE, STATUS, TERMS, PropertyChange, digest
from .property_sync_preview import FIELD_ALIASES, NEW, NUMERIC_FIELDS, REVIEW, TERM_FIELDS, FieldChange, PreviewItem, comparable, first

LOCKBOX = "LOCKBOX CODE CHANGE"
MARKETING = "MARKETING STATUS CHANGE"


def public_evidence(value, protected_values=None):
    """Redact explicit access fields and labelled access notes in general views."""
    if protected_values is None:
        def codes(item):
            if isinstance(item, dict):
                for k, v in item.items():
                    if "lockbox" in k.casefold().replace("_", "") and v not in (None, ""):
                        yield str(v)
                    else:
                        yield from codes(v)
            elif isinstance(item, (list, tuple)):
                for v in item:
                    yield from codes(v)
        protected_values = tuple(codes(value))
    if isinstance(value, dict):
        return {k: "[protected]" if "lockbox" in k.casefold().replace("_", "") else public_evidence(v, protected_values) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public_evidence(v, protected_values) for v in value]
    if isinstance(value, str) and re.search(r"lock\s*box", value, re.I):
        return "[Access details withheld]"
    if isinstance(value, str):
        for code in protected_values:
            value = value.replace(code, "[protected]")
    return value


def event_from_dict(value):
    item = dict(value["evidence"])
    item["changes"] = tuple(FieldChange(**x) for x in item["changes"])
    for key in ("categories", "linked_deals", "review_reasons"):
        item[key] = tuple(item[key])
    item["historical_occurrences"] = tuple(tuple(pair) for pair in item.get("historical_occurrences", ()))
    return PropertyChange(value["event_id"], tuple(value["categories"]), PreviewItem(**item), value.get("detected_at", ""), value.get("priority", "Normal"))


def observe_changes(result, rows, properties, preview, previous, source, secret):
    from .property_sync_preview import HISTORY
    states = dict(previous.source_states)
    by_id = {p.get("id"): p for p in properties}
    current_events, fresh = [], []
    for row, item in zip(rows, preview.items, strict=False):
        if HISTORY in item.categories:
            if item.property_id:
                saved = dict(states.get(item.property_id, {}))
                evidence = dict(saved.get("source_history", {}))
                key = digest([source, item.property_id, "source-classified sold/unavailable"])
                previous_history = evidence.get(key, {})
                occurrences = [list(pair) for pair in previous_history.get("occurrences", [])]
                if [row.tab, row.row] not in occurrences:
                    occurrences.append([row.tab, row.row])
                evidence[key] = {"classification": "source-classified sold/unavailable", "closing_verified": False,
                                 "first_observed_at": previous_history.get("first_observed_at", result.checked_at),
                                 "occurrences": occurrences}
                states[item.property_id] = {**saved, "source_history": evidence}
            continue
        if not item.property_id or REVIEW in item.categories:
            continue
        prop = by_id[item.property_id]
        old = states.get(item.property_id, {})
        old_values = {k: comparable(k, first(prop, aliases)) for k, aliases in FIELD_ALIASES.items()}
        old_values.update(old.get("values", {}))
        codes = [str(x) for x in (row.fields.get("lockbox_code"), prop.get("lockbox_code")) if x not in (None, "")]
        for code in codes:
            old_values["notes"] = old_values.get("notes", "").replace(code, "[protected]")
        old_values["notes"] = public_evidence(old_values.get("notes", ""))
        values = dict(old_values)
        differences = []
        # Ordinary fields stay in the existing evidence system. Lockbox is never a raw field here.
        for key in FIELD_ALIASES:
            value = row.fields.get(key)
            if value in (None, "") or str(value).casefold() in {"n/a", "na", "not applicable"}:
                continue
            value = comparable(key, value)
            if key == "notes":
                for code in codes:
                    value = value.replace(code, "[protected]")
                value = public_evidence(value)
            values[key] = value
            if old_values.get(key, "") != value:
                differences.append(FieldChange(key, old_values.get(key, ""), value))
        if row.marketing_status in {"yellow", "white"}:
            if old_values.get("marketing_status") in {"yellow", "white"} and old_values["marketing_status"] != row.marketing_status:
                differences.append(FieldChange("marketing_status", old_values["marketing_status"], row.marketing_status))
            values["marketing_status"] = row.marketing_status
        previous_lock = old.get("lockbox_fingerprint")
        raw = row.fields.get("lockbox_code")
        if raw is None and row.lockbox_observed:
            raw = ""
        def fingerprint(value):
            return hmac.new(secret.encode(), str(value).encode(), hashlib.sha256).hexdigest()
        if secret and raw is not None:
            if previous_lock is None and prop.get("lockbox_code") is not None:
                previous_lock = fingerprint(prop["lockbox_code"])
            current_lock = fingerprint(raw)
            if previous_lock is not None and current_lock != previous_lock:
                differences.append(FieldChange("lockbox_code", "[protected]", "[protected]"))
        else:
            current_lock = previous_lock
        # Mask known codes if repeated inside a free-text notes field, too.
        for key in ("notes",):
            for code in codes:
                if code in values.get(key, ""):
                    values[key] = values[key].replace(code, "[protected]")
        clean = []
        for change in differences:
            if change.field == "notes":
                a, b = change.current, change.proposed
                for code in codes:
                    a, b = a.replace(code, "[protected]"), b.replace(code, "[protected]")
                a, b = public_evidence(a), public_evidence(b)
                change = FieldChange(change.field, a, b)
            clean.append(change)
        revision = old.get("revision", 0)
        saved = old.get("event")
        if clean:
            revision += 1
            kinds = []
            for change in clean:
                kinds.append(LOCKBOX if change.field == "lockbox_code" else MARKETING if change.field == "marketing_status" else
                             PRICE if change.field == "asking_or_sale_price" else TERMS if change.field in TERM_FIELDS else
                             SOLD_CHANGE if change.field == "availability" and change.proposed == "sold / unavailable" else
                             RETURNED if change.field == "availability" and change.current == "sold / unavailable" and change.proposed == "available" else
                             STATUS if change.field == "availability" else OTHER)
            major = False
            for change in clean:
                if change.field in {"asking_or_sale_price", "monthly_payment", "down_payment", "interest_rate"}:
                    try:
                        a, b = Decimal(change.current), Decimal(change.proposed)
                        major = major or bool(a > 0 and abs(b-a) / a >= Decimal("0.5"))
                    except InvalidOperation:
                        pass
            event = PropertyChange(digest([source, item.property_id, revision, values, current_lock]), tuple(dict.fromkeys(kinds)),
                                   replace(item, categories=tuple(dict.fromkeys(kinds)), changes=tuple(clean)), result.checked_at,
                                   "High" if LOCKBOX in kinds or SOLD_CHANGE in kinds or major else "Normal")
            saved = asdict(event)
            fresh.append(event)
        states[item.property_id] = {**old, "values": values, "lockbox_fingerprint": current_lock, "revision": revision, "event": saved}
        if saved:
            current_events.append(event_from_dict(saved))
    codes = [str(p["lockbox_code"]) for p in (*properties, *(r.fields for r in rows)) if p.get("lockbox_code") not in (None, "")]
    def sanitized(event):
        changes = []
        for c in event.evidence.changes:
            if c.field == "notes":
                a, b = c.current, c.proposed
                for code in codes:
                    a, b = a.replace(code, "[protected]"), b.replace(code, "[protected]")
                a, b = public_evidence(a), public_evidence(b)
                c = replace(c, current=a, proposed=b)
            changes.append(c)
        return replace(event, evidence=replace(event.evidence, changes=tuple(changes)))
    return replace(result, changes=tuple(sanitized(e) for e in result.changes), new_events=tuple(sanitized(e) for e in result.new_events),
                   state=replace(result.state, source_states=states), observed_changes=tuple(current_events), observed_new_events=tuple(fresh))


def change_lines(result, query=""):
    q = query.casefold()
    observed_ids = {e.evidence.property_id for e in result.observed_changes}
    events = (*result.observed_changes, *(e for e in result.changes if not e.evidence.property_id or e.evidence.property_id not in observed_ids))
    def display(field, value):
        if value in (None, ""):
            return "Not recorded"
        if field in NUMERIC_FIELDS:
            try:
                number = Decimal(value)
                if field == "interest_rate":
                    return f"{number:f}%"
                if field in TERM_FIELDS or field == "asking_or_sale_price":
                    return f"${number:,.2f}"
                return f"{number:f}"
            except InvalidOperation:
                return "Needs review"
        return {"yellow": "Actively marketed (yellow)", "white": "Not ready to market (white)",
                "available": "Active", "sold / unavailable": "SOLD / unavailable (source classification)"}.get(value, value)
    lines = []
    for event in events:
        if "new properties" in q and NEW not in event.categories:
            continue
        if "today" in q and (event.detected_at or result.checked_at)[:10] != datetime.now(UTC).date().isoformat():
            continue
        if not event.evidence.changes and not any(word in q for word in ("price", "payment", "lockbox", "marketed")):
            lines.append(f"{event.evidence.address}: {', '.join(event.categories)} · Source: {event.evidence.tab}")
        for change in event.evidence.changes:
            field = change.field
            if "lockbox" in q and field != "lockbox_code":
                continue
            if "price" in q and field != "asking_or_sale_price":
                continue
            if ("monthly payment" in q or "changed payment" in q) and field != "monthly_payment":
                continue
            if "down payment" in q and field != "down_payment":
                continue
            if "marketed" in q and field != "marketing_status":
                continue
            if ("sold" in q or "unavailable" in q) and SOLD_CHANGE not in event.categories:
                continue
            if ("back active" in q or "back available" in q) and RETURNED not in event.categories:
                continue
            description = "Lockbox code changed." if field == "lockbox_code" else f"{field.replace('_', ' ')}: {display(field, change.current)} → {display(field, change.proposed)}"
            lines.append(f"{event.evidence.address} · {event.priority} priority · {', '.join(event.categories)} · {description} · "
                         f"Detected: {event.detected_at or result.checked_at} · Source: {event.evidence.tab}")
    return tuple(lines)
