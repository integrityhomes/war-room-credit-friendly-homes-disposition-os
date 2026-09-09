"""Explicitly approved second baseline: create historical properties only."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .property_baseline import build_baseline_plan
from .property_sync_preview import NEW, REVIEW, SOLD, address_key, compare_properties, read_canonical_records


def historical_baseline_records(rows, existing, *, source_reference_hash):
    # First validate the complete source with the unchanged baseline builder.
    plan = build_baseline_plan(rows, [], source_reference_hash=source_reference_hash)
    if plan.errors or (len(plan.properties), plan.active_count, plan.sold_count, plan.skipped_review) != (155, 29, 126, 300):
        raise ValueError("Source baseline scope failed; no writes allowed.")
    if len(existing) != 29 or any(prop.get("availability") != "Available" for prop in existing):
        raise ValueError("Expected exactly the 29 existing active properties; no writes allowed.")
    preview = compare_properties(rows, existing)
    if preview.counts[NEW] != 126 or preview.counts[SOLD] != 126 or preview.counts[REVIEW] != 300:
        raise ValueError("Current sync preview is outside the approved scope.")
    matched = [item for item in preview.items if item.property_id]
    if len(matched) != 29 or any(item.categories or item.changes for item in matched):
        raise ValueError("Active source matches changed or are ambiguous; stop without writing.")
    records = tuple(item.record for item in plan.properties if item.record["availability"] == "Sold / Unavailable")
    ids = {prop["id"] for prop in existing}
    addresses = {address_key(prop) for prop in existing}
    external_ids = {prop["external_id"] for prop in existing if prop.get("external_id")}
    if len(ids) != 29 or len(addresses) != 29:
        raise ValueError("Existing canonical identities are ambiguous.")
    for record in records:
        UUID(record["id"])
        key, external_id = address_key(record), record.get("external_id")
        metadata = record.get("sync_metadata", {})
        if (
            not key or key in addresses or record["id"] in ids or (external_id and external_id in external_ids)
            or record.get("links") != {} or record.get("entity_type") != "properties"
            or record.get("source") != "cfh-google-sheet" or metadata.get("source_tab") != "SOLD"
            or metadata.get("closing_verified") is not False
            or metadata.get("classification_basis") != "source worksheet membership"
            or metadata.get("source_reference_hash") != source_reference_hash
            or not metadata.get("source_row_hash") or not metadata.get("normalized_facts_hash")
            or metadata.get("normalized_address") != key
            or any(field in record for field in ("stage", "deal_id", "closed_at", "closing_date", "close_date", "closed_date", "closing_status"))
        ):
            raise ValueError("Historical identity or classification check failed; no writes allowed.")
        ids.add(record["id"])
        addresses.add(key)
        if external_id:
            external_ids.add(external_id)
    return plan, records


def import_second_historical_baseline(client: Any, rows, *, source_reference_hash: str, approved_snapshot: str) -> dict[str, int]:
    before = read_canonical_records(client, "properties")
    deals_before = read_canonical_records(client, "deals")
    plan, records = historical_baseline_records(rows, before, source_reference_hash=source_reference_hash)
    if not approved_snapshot or approved_snapshot != plan.snapshot_hash:
        raise PermissionError("Approval must match the current historical baseline snapshot.")
    now = datetime.now(UTC).isoformat()
    proposed = [{**record, "created_at": now, "updated_at": now, "archived": False} for record in records]
    payloads = [json.dumps(record, sort_keys=True).encode("utf-8") for record in proposed]
    bucket = client.storage.from_("commandcore-crm-core")
    for record, payload in zip(proposed, payloads, strict=True):
        bucket.upload(f"properties/{record['id']}.json", payload,
                      file_options={"content-type": "application/json", "upsert": "false"})
    after = read_canonical_records(client, "properties")
    deals_after = read_canonical_records(client, "deals")
    by_id = {record["id"]: record for record in after}
    if len(after) != 155 or any(by_id.get(record["id"]) != record for record in (*before, *proposed)):
        raise RuntimeError("Post-import property verification failed; stop without retrying or deleting.")
    if sorted(deals_before, key=lambda row: row["id"]) != sorted(deals_after, key=lambda row: row["id"]):
        raise RuntimeError("Canonical deals changed during verification; stop and inspect.")
    final_preview = compare_properties(rows, after)
    if final_preview.counts[NEW] != 0 or final_preview.counts[REVIEW] != 300:
        raise RuntimeError("Post-import sync preview verification failed.")
    return {"historical_created": 126, "active_altered": 0, "review_imported": 0,
            "duplicate_candidates_excluded": plan.duplicates_prevented, "existing_active_skipped": 29,
            "duplicate_records_created": 0, "deals_created": 0, "closing_dates_created": 0,
            "deletions": 0, "google_writes": 0, "preview_new": 0}
