"""Local attribution bridge over canonical activities; no ingestion or provider executor.

Evidence receipts and later identity bindings are create-only canonical activities.
Only exact IDs or unique source/external_id pairs resolve identity. No CRM objects
are created, and provider outcome labels are never closing evidence.
"""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

from .channel_tracking import canonical_channel_key
from .commandcore_closing_controls import verified_closing

UNKNOWN = "UNKNOWN"
KINDS = {"contact_id": "contacts", "property_id": "properties", "deal_id": "deals",
         "communication_id": "communications", "task_id": "tasks"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def _activity(kind, key, payload):
    return {"id": "marketing-" + _hash([kind, key]), "source": "corepilot-internal", "internal_only": True,
            "entity_type": "activities", "activity_type": kind, "archived": False, "links": {},
            "execution_key": _hash(payload), "attribution": deepcopy(payload)}


def touch(namespace, event_id, evidence, *, references=None, records=None, observations=None):
    """Prepare a receipt. Stable upstream receipt IDs are mandatory for deduplication.

    References use canonical IDs or {source, external_id}; callers must supply
    verified mappings, never address/name matches. The raw evidence is retained.
    """
    if not str(namespace).strip() or not str(event_id).strip() or not _time(evidence.get("occurred_at")):
        raise ValueError("A source namespace, stable event ID and timezone-aware event time are required")
    refs = deepcopy(references or {})
    if set(refs) - KINDS.keys():
        raise ValueError("Unsupported identity reference")
    medium = str(evidence.get("medium") or "")
    channel = canonical_channel_key(medium) or ("chatgpt_ads" if medium == "chatgpt_ads" else UNKNOWN)
    payload = {"namespace": namespace, "event_id": event_id, "evidence": deepcopy(evidence), "references": refs,
               "channel": channel, **{k: evidence.get(k) or UNKNOWN for k in ("source", "campaign", "post_id", "list_id")}}
    resolved, issues = resolve(refs, records or {})
    payload["marketing_period"] = _period(resolved.get("property_id"), evidence["occurred_at"], records or {}, observations or {}) if not issues else UNKNOWN
    return _activity("marketing_touch", [namespace, event_id], payload)


def tracked_click(event, receipt_id, **kwargs):
    """Adapt existing ClickEvent using its persisted object/receipt ID."""
    refs = dict(kwargs.pop("references", {}) or {})
    if event.property_id:
        refs.setdefault("property_id", {"source": "cfh_properties", "external_id": str(event.property_id)})
    return touch("cfh-click-events", receipt_id, event.to_payload(), references=refs, **kwargs)


def dwelyx_event(event, **kwargs):
    """Preserve the existing signed-event contract; do not reinterpret home.filled."""
    refs = dict(kwargs.pop("references", {}) or {})
    if event.cfh_property_id:
        refs.setdefault("property_id", {"source": "cfh_properties", "external_id": str(event.cfh_property_id)})
    if event.dwelyx_buyer_id:
        refs.setdefault("contact_id", {"source": "dwelyx", "external_id": str(event.dwelyx_buyer_id)})
    return touch("cfh-dwelyx-attribution", event.event_id, event.model_dump(mode="json"), references=refs, **kwargs)


def bind(touch_record, binding_id, references, records, *, observations=None):
    """Prepare an append-only link after exact identity evidence becomes available."""
    if touch_record.get("activity_type") != "marketing_touch" or not binding_id or not references or set(references) - KINDS.keys():
        raise ValueError("A touch, stable binding receipt and supported references are required")
    original = touch_record["attribution"]
    combined = _binding_refs(original["references"], [references], records)
    resolved, issues = resolve(combined, records)
    if issues or any(key not in resolved for key in references):
        raise ValueError("Identity binding is missing, ambiguous or conflicting")
    period = original["marketing_period"]
    if period == UNKNOWN:
        period = _period(resolved.get("property_id"), original["evidence"]["occurred_at"], records, observations or {})
    return _activity("marketing_identity_link", [touch_record["id"], binding_id],
                     {"touch_id": touch_record["id"], "references": deepcopy(references), "marketing_period": period})


def _binding_refs(original, bindings, records):
    # A verified explicit binding may supply a missing legacy crosswalk. Keep
    # resolvable originals in the comparison so conflicting IDs cannot win.
    covered = {k for b in bindings for k in b}
    retained = {k: v for k, v in original.items() if k not in covered or not resolve({k: v}, records)[1]}
    return [retained, *bindings]


def save(client, record):
    """Explicit caller boundary; not wired to live ingestion or UI commands."""
    from .corepilot_internal import create_internal_record
    if record.get("activity_type") not in {"marketing_touch", "marketing_identity_link", "marketing_property_identity"} or record.get("execution_key") != _hash(record.get("attribution")):
        raise ValueError("Invalid attribution activity")
    if record.get("activity_type") == "marketing_property_identity":
        payload = record["attribution"]
        if (set(payload) != {"namespace", "external_id", "property_id", "evidence"}
                or record != _activity("marketing_property_identity", [payload["namespace"], payload["external_id"]], payload)):
            raise ValueError("Invalid property identity activity")
    return create_internal_record(client, "activities", record)


def property_identity(namespace, external_id, property_id, evidence, records):
    """Prepare a reviewed property-only crosswalk; never a lead or marketing period.

    Caller must verify the exact reconciliation and authorization before save.
    Stable source/ID keys make retries create-only, including conflicting targets.
    """
    if (not namespace or not external_id or not property_id or not evidence
            or not _time(evidence.get("verified_at"))
            or evidence.get("match_result") not in {"VERIFIED EXACT", "VERIFIED NORMALIZED ADDRESS MATCH"}):
        raise ValueError("Verified property evidence is required")
    props = [p for p in records.get("properties", ()) if p.get("id") == property_id and not p.get("archived")]
    if len(props) != 1:
        raise ValueError("A unique existing property is required")
    ref = {"source": namespace, "external_id": external_id}
    existing = _property_candidates(ref, records)
    if any(p.get("id") != property_id for p in existing):
        raise ValueError("Conflicting property binding")
    payload = {"namespace": namespace, "external_id": external_id, "property_id": property_id, "evidence": deepcopy(evidence)}
    return _activity("marketing_property_identity", [namespace, external_id], payload)


def _property_candidates(ref, records):
    props = records.get("properties", ())
    ids = {p.get("id") for p in props if ref.get("source") and ref.get("external_id")
           and p.get("source") == ref["source"] and p.get("external_id") == ref["external_id"]}
    for activity in records.get("activities", ()):
        payload = activity.get("attribution", {})
        if (activity.get("source") == "corepilot-internal" and not activity.get("archived")
                and activity.get("activity_type") == "marketing_property_identity"
                and activity.get("execution_key") == _hash(payload)
                and payload.get("namespace") == ref.get("source") and payload.get("external_id") == ref.get("external_id")):
            ids.add(payload.get("property_id"))
    # Missing targets must cause resolution failure, not silently select another.
    return [p for p in props if p.get("id") in ids] + [{"id": None} for pid in ids if not any(p.get("id") == pid for p in props)]


def resolve(references, records):
    """Traverse canonical links, rejecting missing/ambiguous/conflicting identities."""
    pending = list(references if isinstance(references, list) else [references])
    resolved, issues, visited = {}, [], set()
    while pending:
        for key, ref in pending.pop().items():
            if key not in KINDS or not ref:
                continue
            rows = records.get(KINDS[key], ())
            if isinstance(ref, dict):
                candidates = _property_candidates(ref, records) if key == "property_id" else [r for r in rows if ref.get("source") and ref.get("external_id")
                              and r.get("source") == ref["source"] and r.get("external_id") == ref["external_id"]]
            else:
                candidates = [r for r in rows if r.get("id") == ref]
            if len(candidates) != 1 or candidates[0].get("archived") or not candidates[0].get("id"):
                issues.append(f"Unresolved {key}")
                continue
            row = candidates[0]
            if key in resolved and resolved[key] != row["id"]:
                issues.append(f"Conflicting {key}")
                continue
            resolved[key] = row["id"]
            if (key, row["id"]) not in visited:
                visited.add((key, row["id"]))
                pending.extend([{k: row[k] for k in KINDS if row.get(k)}, row.get("links") or {}])
    if not issues and "deal_id" not in resolved and all(k in resolved for k in ("contact_id", "property_id")):
        matches = []
        for deal in records.get("deals", ()):
            if deal.get("archived"):
                continue
            ids, errors = resolve({"deal_id": deal.get("id")}, records)
            if not errors and all(ids.get(k) == resolved[k] for k in ("contact_id", "property_id")):
                matches.append(deal["id"])
        if len(matches) == 1:
            resolved["deal_id"] = matches[0]
        elif len(matches) > 1:
            issues.append("Ambiguous deal_id")
    return ({} if issues else resolved), tuple(sorted(set(issues)))


def _period(property_id, occurred_at, records, observations):
    from .property_sync_preview import FIELD_ALIASES, comparable, first
    props = [p for p in records.get("properties", ()) if p.get("id") == property_id]
    observed = observations.get(property_id) or {}
    start, end, when = (_time(observed.get("marketing_observed_since")), _time(observed.get("checked_at")), _time(occurred_at))
    if (len(props) != 1 or props[0].get("archived") or comparable("availability", first(props[0], FIELD_ALIASES["availability"])) not in {"", "available"}
            or observed.get("status") != "available" or observed.get("marketing_status") != "yellow"
            or not all((start, end, when)) or not start <= when <= end):
        return UNKNOWN
    return "period-" + _hash([property_id, start.isoformat()])


def project(records, observations=None):
    """One row per touch, with conservative verified buyer-closing attribution."""
    activities = [a for a in records.get("activities", ()) if not a.get("archived") and a.get("source") == "corepilot-internal"]
    results = []
    for activity in activities:
        if activity.get("activity_type") != "marketing_touch":
            continue
        payload = activity["attribution"]
        bindings = [a["attribution"] for a in activities if a.get("activity_type") == "marketing_identity_link"
                    and a.get("attribution", {}).get("touch_id") == activity["id"]]
        ids, issues = resolve(_binding_refs(payload["references"], [b["references"] for b in bindings], records), records)
        periods = {v for v in [payload["marketing_period"], *(b["marketing_period"] for b in bindings)] if v != UNKNOWN}
        period = next(iter(periods)) if len(periods) == 1 and not issues else UNKNOWN
        current = _period(ids.get("property_id"), payload["evidence"]["occurred_at"], records, observations or {})
        closings = []
        for transaction in records.get("transactions", ()):
            # Acquisition closing proves ownership/control, not a marketing buyer conversion.
            if transaction.get("archived") or transaction.get("transaction_type") not in {"closing", "purchase_closing"} or not verified_closing(transaction):
                continue
            linked, errors = resolve([{k: transaction[k] for k in KINDS if transaction.get(k)}, transaction.get("links") or {}], records)
            closed, occurred = _time(transaction.get("closed_at")), _time(payload["evidence"]["occurred_at"])
            if (not errors and not issues and all(ids.get(k) and ids[k] == linked.get(k) for k in ("deal_id", "property_id", "contact_id"))
                    and closed and occurred and closed >= occurred and transaction.get("id")):
                closings.append(transaction["id"])
        results.append({"touch_id": activity["id"], **{k: payload[k] for k in ("channel", "source", "campaign", "post_id", "list_id")},
                        **{k: ids.get(k, UNKNOWN) for k in ("property_id", "contact_id", "deal_id")},
                        "marketing_period": period, "current_marketing": period != UNKNOWN and period == current,
                        "result": "VERIFIED_CLOSING" if len(closings) == 1 else UNKNOWN,
                        "closing_id": closings[0] if len(closings) == 1 else UNKNOWN, "issues": issues,
                        "original_evidence": deepcopy(payload["evidence"])})
    return results
