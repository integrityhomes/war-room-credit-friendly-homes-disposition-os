"""Pure marketing checkpoint proposals; never persist or weaken import validation."""

from dataclasses import replace

from .property_sync_preview import REGIONAL_TABS, REVIEW, address_label, compare_properties


def compare_source_identity(rows, properties, *, known_history_keys=()):
    """Reuse canonical matching without optional financial/detail validation."""
    identity_fields = ("address", "property_address", "city", "state", "zip", "zip_code")
    identity_rows = tuple(replace(
        row, fields={key: row.fields[key] for key in identity_fields if key in row.fields},
        issues=tuple(reason for reason in row.issues if reason.startswith((
            "Address is incomplete", "Column headers have not been confirmed", "Row layout needs review",
            "Repeated property_address header", "Repeated address header", "Repeated city header", "Repeated state header", "Repeated zip"))),
    ) for row in rows)
    identity_properties = [{key: prop[key] for key in (*identity_fields, "id", "external_id", "source_record_id", "archived") if key in prop}
                           for prop in properties]
    return compare_properties(identity_rows, identity_properties, known_history_keys=known_history_keys)


def marketing_checkpoint_preview(rows, properties, observations, *, observed_at):
    """Return unapplied patches; observed_at is the verified source-read timestamp.

    The scheduled writer does not call this until activation is approved.
    """
    preview = compare_source_identity(rows, properties)
    eligible = []
    for row, item in zip(rows, preview.items, strict=False):
        if row.tab not in REGIONAL_TABS or row.marketing_status != "yellow" or not item.property_id or REVIEW in item.categories:
            continue
        old = observations.get(item.property_id, {})
        continuous = old.get("status") == "available" and old.get("marketing_status") == "yellow"
        existing_start = old.get("marketing_observed_since") if continuous else None
        patch = {} if existing_start else {
            "status": "available", "marketing_status": "yellow", "marketing_observed_since": observed_at,
            "checked_at": observed_at, "marketing_restarted": True,
            "historical_occurrences": item.historical_occurrences or old.get("historical_occurrences", ()),
        }
        eligible.append({"property_id": item.property_id, "address": address_label(row.fields),
                         "tab": row.tab, "row": row.row, "preserved_start": existing_start,
                         "proposed_checkpoint_patch": patch, "detail_review_reasons": row.issues})
    return {"eligible": eligible, "eligible_count": len(eligible),
            "preserved_count": sum(not item["proposed_checkpoint_patch"] for item in eligible),
            "missing_count": sum(bool(item["proposed_checkpoint_patch"]) for item in eligible),
            "applied": False, "records_written": 0}
