from __future__ import annotations

from typing import Any

APPROVABLE_DOCUMENT_STATUSES = {
    "needs_owner_approval",
    "owner_approval_required",
    "internal_review_ready",
}

LEGAL_TEMPLATE_BLOCKER_STATUS = "needs_approved_legal_template"


def normalized_status(record: dict[str, Any]) -> str:
    return str(record.get("status") or "").strip().lower()


def pending_document(record: dict[str, Any]) -> bool:
    """Return True only when an owner can make a meaningful document decision."""
    return normalized_status(record) in APPROVABLE_DOCUMENT_STATUSES


def legal_template_blocker(record: dict[str, Any]) -> bool:
    """Return True when contract prep is blocked on an approved legal template."""
    return normalized_status(record) == LEGAL_TEMPLATE_BLOCKER_STATUS
