from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .commandcore_contract_controls import legal_template_blocker, pending_document

PENDING_OFFER_STATUS = "draft_pending_owner_approval"
APPROVED_STATUS = "owner_approved"
REJECTED_STATUS = "owner_rejected"


@dataclass(frozen=True, slots=True)
class DealApprovalStatus:
    item_type: str
    item_label: str
    state: str
    next_step: str
    actionable: bool = False
    decided_by: str = ""
    decided_at: str = ""
    decision_reason: str = ""


def text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_status(record: dict[str, Any]) -> str:
    record_status = text(record.get("status")).casefold()
    known_statuses = {
        PENDING_OFFER_STATUS,
        APPROVED_STATUS,
        REJECTED_STATUS,
        "needs_owner_approval",
        "owner_approval_required",
        "internal_review_ready",
        "needs_approved_legal_template",
    }
    if record_status in known_statuses:
        return record_status
    return text(record.get("owner_approval_status")).casefold()


def _offer_label(record: dict[str, Any]) -> str:
    amount = record.get("amount")
    if isinstance(amount, (int, float)):
        return f"Offer recommendation — ${amount:,.0f}"
    return "Offer recommendation"


def _document_label(record: dict[str, Any]) -> str:
    name = text(record.get("name") or record.get("document_type"))
    return name.replace("_", " ").replace("-", " ").title() if name else "Contract or closing document"


def _decision_details(record: dict[str, Any], status: str) -> tuple[str, str, str]:
    decided_by = text(record.get("owner_approved_by") if status == APPROVED_STATUS else record.get("owner_rejected_by"))
    return decided_by, text(record.get("owner_decided_at")), text(record.get("owner_decision_reason"))


def _item(record: dict[str, Any], *, item_type: str) -> DealApprovalStatus | None:
    status = _normalized_status(record)
    label = _offer_label(record) if item_type == "Offer" else _document_label(record)

    if item_type == "Offer" and status == PENDING_OFFER_STATUS:
        return DealApprovalStatus(
            item_type=item_type,
            item_label=label,
            state="Waiting for approval",
            next_step="An owner must review this offer recommendation before the workflow can continue.",
            actionable=True,
        )
    if item_type == "Document" and pending_document({**record, "status": status}):
        return DealApprovalStatus(
            item_type=item_type,
            item_label=label,
            state="Waiting for approval",
            next_step="An owner must review this document before the workflow can continue.",
            actionable=True,
        )
    if item_type == "Document" and legal_template_blocker({**record, "status": status}):
        return DealApprovalStatus(
            item_type=item_type,
            item_label=label,
            state="Needs attention",
            next_step="An approved legal template is required before this can be sent for owner review.",
        )
    if status in {APPROVED_STATUS, REJECTED_STATUS}:
        decided_by, decided_at, reason = _decision_details(record, status)
        approved = status == APPROVED_STATUS
        return DealApprovalStatus(
            item_type=item_type,
            item_label=label,
            state="Approved" if approved else "Rejected",
            next_step=(
                "The owner decision is recorded. Continue through the existing controlled workflow."
                if approved
                else "Review the recorded decision and revise or stop this work before continuing."
            ),
            decided_by=decided_by,
            decided_at=decided_at,
            decision_reason=reason,
        )
    return None


def approval_decision_time_label(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Time not available"
    hour = parsed.hour % 12 or 12
    period = "AM" if parsed.hour < 12 else "PM"
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} at {hour}:{parsed.minute:02d} {period}"


def _decision_rank(item: DealApprovalStatus) -> tuple[int, int, int, int, int, int]:
    if item.decided_at:
        try:
            parsed = datetime.fromisoformat(item.decided_at.replace("Z", "+00:00"))
            return (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute, parsed.second)
        except ValueError:
            pass
    return (1, 1, 1, 0, 0, 0)


def build_deal_approval_status(
    offers: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> list[DealApprovalStatus]:
    items = [
        item
        for item in (
            *(_item(record, item_type="Offer") for record in offers),
            *(_item(record, item_type="Document") for record in documents),
        )
        if item is not None
    ]
    priority = {"Waiting for approval": 0, "Needs attention": 1, "Rejected": 2, "Approved": 3}
    return sorted(items, key=lambda item: (priority[item.state], tuple(-part for part in _decision_rank(item))))
