from __future__ import annotations

from typing import Any

EXECUTED_STATUSES = {"executed", "fully_executed", "signed_executed"}
EXECUTED_DOCUMENT_TYPES = {"executed_contract", "signed_contract"}


def text(value: Any) -> str:
    return str(value or "").strip().lower()


def verified_executed_contract(record: dict[str, Any]) -> bool:
    """Require explicit execution evidence before opening title/closing work."""
    status = text(record.get("status"))
    document_type = text(record.get("document_type"))
    return (
        status in EXECUTED_STATUSES
        and document_type in EXECUTED_DOCUMENT_TYPES
        and record.get("execution_verified") is True
        and record.get("signed_document_attached") is True
        and bool(str(record.get("executed_at") or "").strip())
    )
