"""One read-only review entry per missing physical property; no execution path."""

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime

from .google_sheet_property_rows import normalize_google_sheet_row
from .property_change_attention import public_evidence
from .property_marketing_eligibility import compare_source_identity, marketing_checkpoint_preview
from .property_sync_preview import REGIONAL_TABS, REVIEW, address_key, address_label, compare_properties


def _blocking_issues(row):
    """Accept only already verified textual interpretations, not ambiguous facts."""
    meanings = {d["field"]: d for d in row.source_fields if not d["review"]}
    accepted = set()
    insurance = meanings.get("monthly_insurance", {}).get("normalized")
    if isinstance(insurance, dict) and insurance.get("responsibility") == "buyer":
        accepted.add("Monthly insurance must be a number.")
    update = meanings.get("last_update", {})
    if update.get("raw") and update.get("normalized") == update["raw"]:
        accepted.add("Last update needs review because its date format was not recognized.")
    return tuple(reason for reason in row.issues if reason not in accepted)


def build_import_reconciliation(rows, properties, observations=None, *, observed_at=None):
    observed_at = observed_at or datetime.now(UTC).isoformat()
    # Comparisons retain the original source objects and use existing identity gates.
    reviewed = tuple(replace(row, issues=_blocking_issues(row)) for row in rows)
    compared = compare_properties(reviewed, properties)
    canonical_keys = {address_key(prop) for prop in properties}
    groups = defaultdict(list)
    unresolved = 0
    for row, item in zip(reviewed, compared.items, strict=False):
        if row.tab not in (*REGIONAL_TABS, "SOLD"):
            continue
        complete = all(row.fields.get(key) for key in ("address", "city", "state", "zip_code"))
        key = address_key(row.fields) if complete else ""
        if not key:
            unresolved += 1
        else:
            groups[key].append((row, item))
    entries = []
    yellow_keys = {key for key, pairs in groups.items() if any(row.tab in REGIONAL_TABS and row.marketing_status == "yellow" for row, _ in pairs)}
    yellow_warning_keys = set()
    for key, pairs in groups.items():
        current = [(row, item) for row, item in pairs if row.tab in REGIONAL_TABS]
        yellow = [(row, item) for row, item in current if row.marketing_status == "yellow"]
        white = [(row, item) for row, item in current if row.marketing_status == "white"]
        selected = yellow or white or current or pairs
        row, item = selected[0]
        fields = [dict(d) for d in row.source_fields]
        warnings = [f"Column {d['column']} ({d['field']}): {d['review']}" for d in fields if d["review"] and d["raw"]]
        if key in yellow_keys and (warnings or row.issues):
            yellow_warning_keys.add(key)
        if key in canonical_keys:
            continue
        blockers = list(item.review_reasons)
        if current and not (yellow or white):
            blockers.append("Current inventory color/status is not verified.")
        if len(current) > 1:
            blockers.append("Multiple current source occurrences require identity/detail reconciliation.")
        if item.property_id:
            blockers.append("A canonical record already matches the source ID; creating a second property is prohibited.")
        supplied = dict(row.fields)
        supplied["total_price"] = supplied.pop("asking_or_sale_price", None)
        validation = normalize_google_sheet_row(supplied, source_label=supplied.get("source_label") or "Google Sheet")
        if validation.normalized is None:
            blockers.extend(validation.errors)
        conflicts = any(any(word in reason.casefold() for word in ("duplicate", "multiple", "identity", "different canonical", "source ids disagree")) for reason in blockers)
        classification = "Yellow" if yellow else "White" if white else "Historical-only" if not current else "Other / Review"
        details = {d["field"]: d["normalized"] for d in fields if not d["review"] and d["field"] not in {"unmapped", "lockbox_code"}}
        # No source code is ever included in this preview, including copied notes.
        protected = [str(r.fields["lockbox_code"]) for r, _ in pairs if r.fields.get("lockbox_code")]
        entry = public_evidence({
            "address": address_label(row.fields), "normalized_address": key, "classification": classification,
            "source_tab": row.tab, "source_row": row.row, "identity_verified": True,
            "marketing_verified": bool(yellow or white), "canonical_match": item.property_id or None,
            "duplicate_or_conflict": conflicts or bool(item.property_id),
            "readiness": "BLOCKED — NEEDS REVIEW" if blockers else "READY FOR IMPORT PREVIEW",
            "blocking_reasons": list(dict.fromkeys(blockers)), "field_warnings": warnings,
            "normalized_details": details, "source_fields": [d for d in fields if d["field"] != "lockbox_code"],
            "access_code_present": any(bool(r.fields.get("lockbox_code")) or any(d["field"] == "lockbox_code" and d["raw"] for d in r.source_fields) for r, _ in pairs),
            "historical_occurrences": [{"tab": r.tab, "row": r.row, "classification": "Source-classified sold/unavailable", "closing_verified": False}
                                       for r, _ in pairs if r.tab == "SOLD"],
            "source_occurrences": [{"tab": r.tab, "row": r.row} for r, _ in pairs],
        }, protected)
        # Presence only, never even a masked old/new code comparison in a detail table.
        entry["source_fields"] = [d for d in entry["source_fields"] if d["field"] != "lockbox_code"]
        entries.append(entry)
    order = {"Yellow": 0, "White": 1, "Historical-only": 2, "Other / Review": 3}
    entries.sort(key=lambda entry: (order[entry["classification"]], entry["normalized_address"]))
    summary = {}
    for label in order:
        subset = [e for e in entries if e["classification"] == label]
        ready = sum(not e["blocking_reasons"] for e in subset)
        summary[label] = {"total": len(subset), "ready": ready, "blocked": len(subset) - ready}
    clocks = marketing_checkpoint_preview(rows, properties, observations or {}, observed_at=observed_at)
    return {"observed_at": observed_at, "properties": entries, "total_missing": len(entries), "summary": summary,
            "total_ready": sum(not e["blocking_reasons"] for e in entries),
            "duplicate_conflict_count": sum(e["duplicate_or_conflict"] for e in entries),
            "properties_with_field_warnings": sum(bool(e["field_warnings"]) for e in entries),
            "field_warning_count": sum(len(e["field_warnings"]) for e in entries),
            "manual_review_count": sum(bool(e["blocking_reasons"] or e["field_warnings"]) for e in entries),
            "blocking_reason_counts": dict(Counter(reason for e in entries for reason in e["blocking_reasons"])),
            "unresolved_or_nonproperty_rows_excluded": unresolved,
            "yellow_total": len(yellow_keys), "yellow_canonical": len(yellow_keys & canonical_keys),
            "yellow_missing": len(yellow_keys - canonical_keys), "yellow_with_warnings": len(yellow_warning_keys),
            "missing_marketing_clocks": [{k: e[k] for k in ("property_id", "address", "tab", "row")} for e in clocks["eligible"] if e["proposed_checkpoint_patch"]],
            "import_enabled": False, "records_written": 0, "deletions": 0, "deals_created": 0}


def load_import_reconciliation(secrets):
    from supabase import create_client

    from .property_baseline import load_baseline_source
    from .property_change_cache import cache_path, read_cache
    from .property_sync_preview import read_canonical_records

    rows, _ = load_baseline_source(secrets, include_marketing=True, verified_format_recovery=True)
    client = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_SERVICE_ROLE_KEY"])
    properties = read_canonical_records(client, "properties")
    observations = read_cache(cache_path(secrets)).get("inventory_observations", {})
    result = build_import_reconciliation(rows, properties, observations)
    result["current_inventory"] = build_current_inventory_candidates(rows, properties, observations, reconciliation=result)
    return result


def build_current_inventory_candidates(rows, properties, observations=None, *, reconciliation=None):
    """Current inventory creation eligibility only. No imports or clock writes."""
    full = reconciliation if reconciliation is not None else build_import_reconciliation(rows, properties, observations)
    matches = compare_source_identity(rows, properties)
    by_location = {(row.tab, row.row): item for row, item in zip(rows, matches.items, strict=False)}
    entries = []
    for original in full["properties"]:
        if original["classification"] not in {"Yellow", "White"}:
            continue
        item = by_location[original["source_tab"], original["source_row"]]
        blockers = list(item.review_reasons) if REVIEW in item.categories else []
        if item.property_id:
            blockers.append("Canonical identity already exists; a second physical property must not be created.")
        warnings = list(original["field_warnings"])
        # Missing asking-price headers carry no value to interpret; preserve that
        # fact as a warning and never substitute purchase price.
        for reason in original["blocking_reasons"]:
            if reason.startswith("Sales price column is not confirmed"):
                warnings.append(reason)
        entries.append({
            **original, "identity_verified": not blockers, "duplicate_safe": not blockers,
            "ready_for_canonical_creation": not blockers, "blocking_reasons": blockers,
            "field_warnings": list(dict.fromkeys(warnings)),
            "readiness": "READY FOR CANONICAL CREATION PREVIEW" if not blockers else "BLOCKED — IDENTITY / DUPLICATE REVIEW",
            "prior_full_validation_blockers": original["blocking_reasons"],
        })
    summary = {}
    for classification in ("Yellow", "White"):
        subset = [e for e in entries if e["classification"] == classification]
        summary[classification] = {
            "total": len(subset), "identity_safe": sum(e["ready_for_canonical_creation"] for e in subset),
            "blocked": sum(not e["ready_for_canonical_creation"] for e in subset),
            "field_warning_only": sum(e["ready_for_canonical_creation"] and bool(e["field_warnings"]) for e in subset),
            "field_warning_count": sum(len(e["field_warnings"]) for e in subset),
            "previously_blocked_detail_only": sum(e["ready_for_canonical_creation"] and bool(e["prior_full_validation_blockers"]) for e in subset),
        }
    clocks = marketing_checkpoint_preview(rows, properties, observations or {}, observed_at=full["observed_at"])
    return {"observed_at": full["observed_at"], "properties": entries, "summary": summary,
            "total_candidates": len(entries), "total_ready": sum(e["ready_for_canonical_creation"] for e in entries),
            "field_warning_count": sum(len(e["field_warnings"]) for e in entries),
            "historical_only_included": 0, "import_enabled": False, "records_written": 0,
            "checkpoint_proposals": [e for e in clocks["eligible"] if e["proposed_checkpoint_patch"]],
            "existing_clocks_preserved": clocks["preserved_count"], "checkpoints_written": 0}
