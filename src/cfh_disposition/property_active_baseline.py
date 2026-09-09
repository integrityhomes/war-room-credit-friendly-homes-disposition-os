"""Explicitly approved first active-only load into the existing CRM JSON bucket.

The general baseline UI remains disabled. This operation never updates a record
and deliberately stops on a partial failure rather than retrying or rolling back.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from .property_baseline import BaselinePlan
from .property_sync_preview import REGIONAL_TABS, address_key, read_canonical_records


def active_baseline_records(plan: BaselinePlan) -> tuple[dict[str, Any], ...]:
    if plan.errors or (len(plan.properties), plan.active_count, plan.sold_count, plan.skipped_review) != (155, 29, 126, 300):
        raise ValueError("Validated baseline scope failed; no writes allowed.")
    records = tuple(item.record for item in plan.properties if item.record["availability"] == "Available")
    addresses, ids, external_ids = set(), set(), set()
    for record in records:
        metadata = record.get("sync_metadata", {})
        key = address_key(record)
        identity = record.get("id", "")
        UUID(identity)  # Never allow a supplied storage path.
        external_id = record.get("external_id")
        if (
            not key or key in addresses or identity in ids or (external_id and external_id in external_ids)
            or record.get("entity_type") != "properties" or record.get("source") != "cfh-google-sheet"
            or record.get("links") != {} or "stage" in record or "closed_at" in record
            or metadata.get("source_tab") not in REGIONAL_TABS
            or not metadata.get("source_reference_hash") or not metadata.get("source_row_hash")
            or not metadata.get("normalized_facts_hash") or metadata.get("normalized_address") != key
            or metadata.get("closing_verified") is not False
        ):
            raise ValueError("Active property identity or source checks failed; no writes allowed.")
        addresses.add(key)
        ids.add(identity)
        if external_id:
            external_ids.add(external_id)
    return records


def import_first_active_baseline(client: Any, plan: BaselinePlan, *, approved_snapshot: str) -> dict[str, int]:
    """Requires the exact freshly reviewed snapshot and an empty canonical baseline.

    Uses the CRM's existing properties/<id>.json contract, with Storage's atomic
    create-only operation instead of the CRM upsert that can overwrite records.
    """
    if not approved_snapshot or approved_snapshot != plan.snapshot_hash:
        raise PermissionError("Explicit approval must match this baseline snapshot.")
    records = active_baseline_records(plan)
    before = read_canonical_records(client, "properties")
    deals_before = read_canonical_records(client, "deals")
    if before:
        raise ValueError("Canonical properties are not empty; first import stopped without writing.")
    bucket = client.storage.from_("commandcore-crm-core")
    proposed = []
    now = datetime.now(UTC).isoformat()
    # Serialize every record before the first write. Same metadata as CRM normalizeRecord.
    for record in records:
        proposed.append({**record, "created_at": now, "updated_at": now, "archived": False})
    payloads = [json.dumps(record, sort_keys=True).encode("utf-8") for record in proposed]
    for record, payload in zip(proposed, payloads, strict=True):
        bucket.upload(f"properties/{record['id']}.json", payload,
                      file_options={"content-type": "application/json", "upsert": "false"})
    after = read_canonical_records(client, "properties")
    deals_after = read_canonical_records(client, "deals")
    by_id = {record["id"]: record for record in after}
    if len(after) != 29 or any(by_id.get(record["id"]) != record for record in proposed):
        raise RuntimeError("Post-import property verification failed; stop and inspect without retrying.")
    if sorted(deals_before, key=lambda row: row["id"]) != sorted(deals_after, key=lambda row: row["id"]):
        raise RuntimeError("Canonical deals changed during verification; stop and inspect.")
    return {"created": 29, "active": 29, "sold_imported": 0, "review_imported": 0,
            "duplicate_candidates_excluded": plan.duplicates_prevented, "duplicate_records_created": 0,
            "deals_created": 0, "deletions": 0, "google_writes": 0}
