"""In-memory CommandCore CRM backend for local demo mode.

Mirrors the ``commandcore-crm-core`` edge-function action surface
(list / get / upsert / archive) without network or Supabase.
"""

from __future__ import annotations

import copy
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

ENTITY_TYPES = frozenset(
    {
        "contacts",
        "properties",
        "deals",
        "activities",
        "communications",
        "tasks",
        "offers",
        "documents",
        "transactions",
    }
)

MAX_LIST = 500


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_segment(value: Any) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in _text(value))
    return (cleaned[:180] or "unknown")


def deterministic_import_id(entity: str, source: str, external_id: str) -> str:
    """Match the edge function's FNV-1a style import id for stable fixtures."""
    payload = f"{entity}:{source.lower()}:{external_id.lower()}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:12]
    return f"imp-{digest}-{_safe_segment(external_id)[:72]}"


def _normalize_record(entity: str, supplied: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
    now = _now()
    source = _text(supplied.get("source") or (existing or {}).get("source") or "commandcore")
    external_id = _text(supplied.get("external_id") or (existing or {}).get("external_id"))
    singular = entity[:-1] if entity.endswith("s") else entity
    supplied_id = _text(supplied.get("id") or supplied.get(f"{singular}_id"))
    if supplied_id:
        record_id = supplied_id
    elif external_id:
        record_id = deterministic_import_id(entity, source, external_id)
    else:
        record_id = str(uuid.uuid4())

    if isinstance(supplied.get("links"), dict):
        links = dict(supplied["links"])
    elif existing and isinstance(existing.get("links"), dict):
        links = dict(existing["links"])
    else:
        links = {}

    base = dict(existing or {})
    base.update(supplied)
    base.update(
        {
            "id": record_id,
            "entity_type": entity,
            "source": source,
            "external_id": external_id or None,
            "links": links,
            "created_at": _text((existing or {}).get("created_at") or supplied.get("created_at")) or now,
            "updated_at": now,
            "archived": supplied.get("archived") is True,
        }
    )
    return base


class DemoCrmBackend:
    """Process CRM payloads the same way pages call ``commandcore-crm-core``."""

    mode = "demo"

    def __init__(self, seed: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._records: dict[str, dict[str, dict[str, Any]]] = {entity: {} for entity in ENTITY_TYPES}
        if seed:
            for entity, rows in seed.items():
                if entity not in ENTITY_TYPES:
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    normalized = _normalize_record(entity, dict(row), None)
                    self._records[entity][normalized["id"]] = normalized

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = _text(payload.get("action") or "upsert").lower()
        entity = _text(payload.get("entity")).lower()
        if entity not in ENTITY_TYPES:
            return {
                "ok": False,
                "error": "valid_entity_required",
                "entity_types": sorted(ENTITY_TYPES),
            }

        if action == "get":
            record_id = _text(payload.get("id"))
            if not record_id:
                return {"ok": False, "error": "id_required"}
            record = self._records[entity].get(record_id)
            if not record:
                return {"ok": False, "error": "record_not_found", "entity": entity, "id": record_id}
            return {"ok": True, "entity": entity, "record": copy.deepcopy(record)}

        if action == "list":
            try:
                limit = int(payload.get("limit") or 100)
            except (TypeError, ValueError):
                limit = 100
            limit = min(max(limit, 1), MAX_LIST)
            include_archived = payload.get("include_archived") is True
            rows = list(self._records[entity].values())
            rows.sort(key=lambda item: _text(item.get("updated_at")), reverse=True)
            if not include_archived:
                rows = [row for row in rows if row.get("archived") is not True]
            records = [copy.deepcopy(row) for row in rows[:limit]]
            return {"ok": True, "entity": entity, "records": records, "count": len(records)}

        if action == "archive":
            record_id = _text(payload.get("id"))
            if not record_id:
                return {"ok": False, "error": "id_required"}
            existing = self._records[entity].get(record_id)
            if not existing:
                return {"ok": False, "error": "record_not_found", "entity": entity, "id": record_id}
            archived = {
                **existing,
                "archived": True,
                "archived_at": _now(),
                "updated_at": _now(),
            }
            self._records[entity][record_id] = archived
            return {"ok": True, "entity": entity, "record": copy.deepcopy(archived)}

        if action == "upsert":
            supplied = payload.get("record")
            if not isinstance(supplied, dict) or not supplied:
                return {"ok": False, "error": "record_required"}
            source = _text(supplied.get("source") or "commandcore")
            external_id = _text(supplied.get("external_id"))
            candidate_id = _text(supplied.get("id")) or (
                deterministic_import_id(entity, source, external_id) if external_id else ""
            )
            existing = self._records[entity].get(candidate_id) if candidate_id else None
            record = _normalize_record(entity, dict(supplied), existing)
            self._records[entity][record["id"]] = record
            return {
                "ok": True,
                "entity": entity,
                "created": existing is None,
                "record": copy.deepcopy(record),
                "destructive_delete_used": False,
                "external_action_started": False,
            }

        if action == "migration_preview":
            return {
                "ok": True,
                "action": "migration_preview",
                "entity": entity,
                "input_count": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "duplicate_count": 0,
                "would_create": 0,
                "would_update": 0,
                "errors": [],
                "migration_bulk_apply_enabled": False,
                "records_written": 0,
                "source_records_modified": False,
                "destructive_action_started": False,
                "external_action_started": False,
            }

        return {"ok": False, "error": "unsupported_action"}


class _DemoFunctions:
    def __init__(self, backend: DemoCrmBackend) -> None:
        self._backend = backend

    def invoke(self, name: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options or {}
        body = options.get("body") if isinstance(options, dict) else None
        if name != "commandcore-crm-core":
            return {
                "ok": False,
                "error": "demo_mode_function_unavailable",
                "function": name,
                "message": "Connect Supabase to use this CommandCore function.",
            }
        if not isinstance(body, dict):
            return {"ok": False, "error": "invalid_json"}
        return self._backend.handle(body)


class _DemoStorageBucket:
    def remove(self, _paths: list[str]) -> None:
        raise RuntimeError("Connect Supabase before using contract file storage.")

    def from_(self, _bucket: str) -> _DemoStorageBucket:
        return self


class DemoSupabaseShim:
    """Minimal stand-in for the Supabase client used by CRM pages."""

    def __init__(self, backend: DemoCrmBackend | None = None) -> None:
        self._backend = backend or DemoCrmBackend()
        self.functions = _DemoFunctions(self._backend)
        self.storage = _DemoStorageBucket()

    @property
    def backend(self) -> DemoCrmBackend:
        return self._backend
