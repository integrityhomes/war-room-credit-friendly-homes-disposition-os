from __future__ import annotations

from typing import Any

CLOSED_TRANSACTION_STATUSES = {"closed", "completed", "settled"}
CLOSING_TRANSACTION_TYPES = {"acquisition_closing", "purchase_closing", "closing"}


def normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def verified_closing(record: dict[str, Any]) -> bool:
    """Require explicit closing evidence before disposition work can open."""
    return (
        normalized(record.get("status")) in CLOSED_TRANSACTION_STATUSES
        and normalized(record.get("transaction_type")) in CLOSING_TRANSACTION_TYPES
        and record.get("closing_verified") is True
        and record.get("ownership_or_control_confirmed") is True
        and bool(str(record.get("closed_at") or "").strip())
    )
