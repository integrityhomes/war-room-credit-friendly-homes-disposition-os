"""Snapshot-approved current inventory creation. No live entry point is enabled."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .commandcore_property_inventory import deterministic_property_id
from .property_baseline import _hash, _json
from .property_change_attention import public_evidence
from .property_change_cache import exclusive_check
from .property_import_reconciliation import build_current_inventory_candidates
from .property_marketing_eligibility import compare_source_identity
from .property_sync_preview import FIELD_ALIASES, HISTORY, REGIONAL_TABS, REVIEW, address_key, read_canonical_records


@dataclass(frozen=True)
class CurrentImportPlan:
    records_json: tuple[str, ...]
    snapshot_hash: str

    @property
    def records(self):
        return tuple(json.loads(record) for record in self.records_json)


def prepare_current_import(rows, *, source_reference_hash):
    """Build only identity-safe current records; retain detail warnings privately."""
    if not source_reference_hash:
        raise ValueError("Verified source fingerprint required")
    candidates = build_current_inventory_candidates(rows, [])
    if any(not item["ready_for_canonical_creation"] for item in candidates["properties"]):
        raise ValueError("Current identity or duplicate blockers require review")
    records = []
    for item in candidates["properties"]:
        row = next(r for r in rows if (r.tab, r.row) == (item["source_tab"], item["source_row"]))
        identity_key = address_key(row.fields)  # Identity never comes from redacted display text.
        if row.tab not in REGIONAL_TABS or row.marketing_status not in {"yellow", "white"} or row.fields.get("availability") != "Available":
            raise ValueError("Only verified current inventory may be created")
        # These are already parsed canonical facts. Never promote arbitrary notes,
        # dates, raw source cells, or unknown values to business fields.
        facts = {key: row.fields.get(key) for key in FIELD_ALIASES if key != "lockbox_code"}
        facts.update({key: row.fields[key] for key in ("address", "city", "state")})
        facts["zip"] = row.fields["zip_code"]
        for key in ("seller_entity", "marketing_client"):
            if row.fields.get(key):
                facts[key] = row.fields[key]
        protected = [str(r.fields["lockbox_code"]) for r in rows if r.fields.get("lockbox_code")]
        for key in ("notes", "legal_description", "photo_link", "seller_entity", "marketing_client"):
            # Free-text access details cannot become ordinary property facts.
            # Do not redact identities or numeric facts merely because digits
            # coincide with an unrelated access code.
            if public_evidence(facts.get(key), protected) != facts.get(key):
                facts[key] = None
        # Safe evidence is produced by the existing protected reconciliation view.
        metadata = {"source_reference_hash": source_reference_hash, "source_tab": row.tab, "source_row": row.row,
                    "source_row_hash": row.fields.get("source_row_hash"), "normalized_address": identity_key,
                    "normalized_facts_hash": _hash(facts), "classification_basis": "verified current inventory row fill",
                    "marketing_status": row.marketing_status, "closing_verified": False,
                    "source_fields": item["source_fields"], "field_warnings": item["field_warnings"],
                    "historical_occurrences": item["historical_occurrences"], "access_code_present": item["access_code_present"]}
        record = {**facts, "id": deterministic_property_id("cfh-google-sheet:" + source_reference_hash, "address:" + identity_key),
                  "entity_type": "properties", "source": "cfh-google-sheet", "external_id": row.external_id or None,
                  "source_record_id": row.fields.get("source_record_id"), "links": {}, "sync_metadata": metadata}
        records.append(record)
    encoded = tuple(_json(r) for r in sorted(records, key=lambda r: r["id"]))
    return CurrentImportPlan(encoded, _hash(encoded))


def execute_current_import(client, rows, *, source_reference_hash, approved_snapshot, lock_path):
    """Create-only canonical transport; caller must supply a freshly read source.

    No scheduler/UI invokes this. Approval is bound to every proposed fact and
    warning. A partial failure stops, without rollback or automatic retries.
    """
    plan = prepare_current_import(rows, source_reference_hash=source_reference_hash)
    if not approved_snapshot or approved_snapshot != plan.snapshot_hash:
        raise PermissionError("Separate approval must match the fresh current-inventory snapshot")
    with exclusive_check(lock_path):
        before = read_canonical_records(client, "properties")
        deals_before = read_canonical_records(client, "deals")
        matched = compare_source_identity(rows, before)
        locations = {(r.tab, r.row): item for r, item in zip(rows, matched.items, strict=False) if HISTORY not in item.categories}
        pending, duplicates = [], 0
        for record in plan.records:
            metadata = record["sync_metadata"]
            item = locations[metadata["source_tab"], metadata["source_row"]]
            if REVIEW in item.categories:
                raise ValueError("Fresh canonical identity conflict; nothing written")
            if item.property_id:
                duplicates += 1
                continue
            if any(p.get("id") == record["id"] for p in before):
                raise ValueError("Canonical ID collision; nothing written")
            pending.append(record)
        now = datetime.now(UTC).isoformat()
        payloads = [{**record, "created_at": now, "updated_at": now, "archived": False} for record in pending]
        encoded = [json.dumps(record, sort_keys=True).encode() for record in payloads]
        bucket = client.storage.from_("commandcore-crm-core")
        for record, payload in zip(payloads, encoded, strict=True):
            bucket.upload(f"properties/{record['id']}.json", payload, file_options={"content-type": "application/json", "upsert": "false"})
        after = read_canonical_records(client, "properties")
        by_id = {r["id"]: r for r in after}
        if len(after) != len(before) + len(payloads) or any(by_id.get(r["id"]) != r for r in [*before, *payloads]):
            raise RuntimeError("Canonical verification failed; stop without retrying")
        if read_canonical_records(client, "deals") != deals_before:
            raise RuntimeError("Deal evidence changed concurrently; stop and review")
        return {"created": len(payloads), "duplicates_prevented": duplicates,
                "yellow": sum(r["sync_metadata"]["marketing_status"] == "yellow" for r in payloads),
                "white": sum(r["sync_metadata"]["marketing_status"] == "white" for r in payloads),
                "historical_only_imported": 0, "deals_created": 0, "deletions": 0, "sheet_writes": 0, "checkpoints_written": 0}


def prepare_minimal_owner_identity(address, city, state, *, source_reference_hash, provenance, zip_code=None):
    """Explicit owner-confirmed identity; optional property facts stay unknown."""
    from .property_sync_preview import address_label
    if not provenance or not source_reference_hash or not all(isinstance(v, str) and v.strip() for v in (address, city, state)):
        raise ValueError("Verified address and provenance required")
    fields = {"address": address, "city": city, "state": state.upper(), "zip": zip_code}
    key = address_key({**fields, "zip": "00000"})  # Sentinel used only for identity comparison; never a stored ZIP.
    if not key:
        raise ValueError("Unambiguous street/city/state required")
    return {**{k: None for k in FIELD_ALIASES}, **fields,
            "id": deterministic_property_id("cfh-owner-confirmed:" + source_reference_hash, key),
            "entity_type": "properties", "source": "cfh-google-sheet", "external_id": None,
            "availability": "Available", "archived": False, "links": {},
            "sync_metadata": {"source_reference_hash": source_reference_hash, "identity_only": True,
                              "owner_confirmed_fields": ["address", "city", "state", "availability"],
                              "provenance": provenance, "closing_verified": False,
                              "verified_address": address_label(fields)}}


def minimal_identity_matches(record, properties):
    """Ignore optional ZIP, never house number/direction/street/city/state."""
    key = address_key({**record, "zip": "00000", "zip_code": "00000"})
    return [p for p in properties if key and address_key({**p, "zip": "00000", "zip_code": "00000"}) == key]


def ensure_minimal_owner_identity(client, record, *, lock_path, owner_approved=False):
    """Use canonical create-only storage under the same existing source lock."""
    if not owner_approved or not record.get("sync_metadata", {}).get("identity_only"):
        raise PermissionError("Explicit minimal-identity approval required")
    with exclusive_check(lock_path):
        before = read_canonical_records(client, "properties")
        matches = minimal_identity_matches(record, before)
        if len(matches) > 1 or any(p.get("archived") for p in matches):
            raise ValueError("Ambiguous or archived canonical identity")
        if matches:
            return matches[0], False
        if any(p.get("id") == record["id"] for p in before):
            raise ValueError("Canonical ID collision")
        now = datetime.now(UTC).isoformat()
        payload = {**record, "created_at": now, "updated_at": now}
        path = "properties/" + record["id"] + ".json"
        bucket = client.storage.from_("commandcore-crm-core")
        try:
            bucket.upload(path, json.dumps(payload, sort_keys=True).encode(), file_options={"content-type": "application/json", "upsert": "false"})
        except Exception:
            existing = json.loads(bucket.download(path))
            if any(existing.get(k) != v for k, v in record.items()):
                raise RuntimeError("Uncertain create cannot be verified") from None
            return existing, False
        if json.loads(bucket.download(path)) != payload:
            raise RuntimeError("Canonical identity read-back mismatch")
        return payload, True
