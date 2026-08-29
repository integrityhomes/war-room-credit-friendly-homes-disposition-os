from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FINAL_OUTCOME_TYPES = {
    "disposition_completion",
    "buyer_sale_completion",
    "owner_finance_completion",
    "owner_finance_activation",
}

FINAL_OUTCOME_STATUSES = {
    "completed",
    "closed",
    "settled",
    "activated",
    "active",
}


def verified_final_outcome(record: Mapping[str, Any]) -> bool:
    """Return True only when an explicit final deal outcome has been verified.

    A marketing Sold/Filled flag is intentionally insufficient. The transaction
    must explicitly represent the completed disposition/owner-finance outcome,
    confirm the buyer contract was executed, and carry a verified effective
    timestamp.
    """

    outcome_type = str(record.get("transaction_type") or "").strip().lower()
    status = str(record.get("status") or "").strip().lower()
    effective_at = str(
        record.get("completion_effective_at")
        or record.get("closed_at")
        or record.get("activated_at")
        or ""
    ).strip()

    return (
        outcome_type in FINAL_OUTCOME_TYPES
        and status in FINAL_OUTCOME_STATUSES
        and record.get("completion_verified") is True
        and record.get("buyer_contract_executed") is True
        and bool(effective_at)
    )
