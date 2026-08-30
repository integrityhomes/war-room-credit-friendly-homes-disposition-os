from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_ENTITIES = ("contacts", "properties", "deals")


@dataclass(frozen=True, slots=True)
class StagedCrmRow:
    entity: str
    identity_key: str
    record: dict[str, Any]
    approved: bool
    internal_only: bool
    source_payload_preserved: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "identity_key": self.identity_key,
            "record": dict(self.record),
            "approved": self.approved,
            "internal_only": self.internal_only,
            "source_payload_preserved": self.source_payload_preserved,
        }


def stage_fixture_rows(fixture: dict[str, Any]) -> list[StagedCrmRow]:
    """Build a network-free preview shaped like the existing CRM import staging/commit boundary."""

    contact = fixture["contact"]
    property_record = fixture["property"]
    deal = fixture["deal"]
    rows = [
        StagedCrmRow(
            entity="contacts",
            identity_key=str(contact["id"]),
            record={
                "external_id": contact["id"],
                "name": contact["name"],
                "phone": contact["phone"],
                "email": contact["email"],
                "internal_only": True,
                "fixture_source": contact["fixture_source"],
            },
            approved=True,
            internal_only=True,
        ),
        StagedCrmRow(
            entity="properties",
            identity_key=str(property_record["id"]),
            record={
                "external_id": property_record["id"],
                "address": property_record["address"],
                "city": property_record["city"],
                "state": property_record["state"],
                "zip": property_record["zip"],
                "county": property_record["county"],
                "parcel_id": property_record["parcel_number"],
                "internal_only": True,
                "fixture_source": property_record["fixture_source"],
            },
            approved=True,
            internal_only=True,
        ),
        StagedCrmRow(
            entity="deals",
            identity_key=str(deal["id"]),
            record={
                "external_id": deal["id"],
                "title": property_record["address"],
                "status": deal["status"],
                "source": deal["lead_type"],
                "asking_price": deal["asking_price"],
                "offer_price": fixture["offer"]["starting_offer"],
                "arv": deal["arv"],
                "estimated_repairs": deal["repairs"],
                "internal_only": True,
                "external_action_started": False,
                "fixture_source": deal["fixture_source"],
                "links": {
                    "contact_identity_key": contact["id"],
                    "property_identity_key": property_record["id"],
                },
            },
            approved=True,
            internal_only=True,
        ),
    ]
    if any(row.entity not in SUPPORTED_ENTITIES for row in rows):
        raise ValueError("Harness CRM staging produced an unsupported entity.")
    if any(not row.identity_key or not row.internal_only for row in rows):
        raise ValueError("Harness CRM staging must remain stable and internal_only.")
    return rows


def preview_fixture_commit(rows: list[StagedCrmRow]) -> dict[str, Any]:
    """Return a deterministic no-write preview using the existing import-commit vocabulary."""

    approved = [row for row in rows if row.approved]
    by_entity: dict[str, dict[str, int]] = {}
    for row in approved:
        stats = by_entity.setdefault(row.entity, {"rows": 0, "would_create": 0, "would_update": 0})
        stats["rows"] += 1
        stats["would_create"] += 1
    return {
        "apply_requested": False,
        "approved_rows": len(approved),
        "rejected_rows": len(rows) - len(approved),
        "ready_to_commit": len(approved),
        "entities": by_entity,
        "would_create": len(approved),
        "would_update": 0,
        "invalid_count": 0,
        "duplicate_count": 0,
        "records_written": 0,
        "source_records_modified": False,
        "source_payload_preserved": all(row.source_payload_preserved for row in rows),
        "apply_guard_ready": True,
        "destructive_delete_used": False,
        "external_action_started": False,
    }
