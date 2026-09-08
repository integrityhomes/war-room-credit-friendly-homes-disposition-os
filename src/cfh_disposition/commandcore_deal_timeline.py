"""Read-only Deal timeline and next-action projections over canonical CRM records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .commandcore_approval_status import DealApprovalStatus, build_deal_approval_status
from .commandcore_deal_summary import next_open_task

TIMESTAMP_FIELDS = (
    "occurred_at",
    "completed_at",
    "sent_at",
    "signed_at",
    "received_at",
    "created_at",
    "updated_at",
    "requested_at",
    "timestamp",
)


@dataclass(frozen=True, slots=True)
class DealTimelineEvent:
    event_key: str
    occurred_at: datetime | None
    occurred_at_label: str
    title: str
    detail: str
    category: str
    source_entity: str
    source_record_id: str


@dataclass(frozen=True, slots=True)
class DealNextAction:
    current_stage: str
    waiting_for: str
    recommended_action: str
    responsible_person: str
    due_date: str
    blocker: str
    approval_needed: bool


def _text(value: Any) -> str:
    return str(value or "").strip()


def _timestamp(record: dict[str, Any]) -> datetime | None:
    for field in TIMESTAMP_FIELDS:
        raw = _text(record.get(field))
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(raw[:10])
            except ValueError:
                continue
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _date_label(value: datetime | None) -> str:
    if value is None:
        return "Date not recorded"
    hour = value.hour % 12 or 12
    period = "AM" if value.hour < 12 else "PM"
    return f"{value.strftime('%b')} {value.day}, {value.year} at {hour}:{value.minute:02d} {period}"


def _friendly(value: Any, fallback: str) -> str:
    text = _text(value).replace("_", " ").replace("-", " ")
    return text.title() if text else fallback


def _event_text(entity: str, record: dict[str, Any]) -> tuple[str, str, str]:
    status = _text(record.get("status")).casefold()
    if entity == "activities":
        return (
            _friendly(record.get("title") or record.get("activity_type"), "Activity recorded"),
            _text(record.get("summary")) or "An activity was recorded on this deal.",
            "Activity",
        )
    if entity == "communications":
        direction = _text(record.get("direction")).casefold()
        title = "Communication sent" if direction == "outbound" else "Communication received"
        channel = _friendly(record.get("channel"), "Communication")
        classification = _text(record.get("nevaeh_classification") or record.get("classification"))
        detail = _text(record.get("summary")) or (
            f"{channel} communication · {classification}" if classification else f"{channel} communication recorded."
        )
        return title, detail, "Communication"
    if entity == "tasks":
        complete = status in {"done", "completed", "closed"}
        return (
            "Task completed" if complete else "Task added",
            _text(record.get("title")) or "Deal task recorded.",
            "Task",
        )
    if entity == "offers":
        if status in {"draft_pending_owner_approval", "needs_owner_approval"}:
            return "Approval requested", "An offer is waiting for owner approval.", "Approval"
        if status in {"owner_approved", "owner_rejected"}:
            return "Approval completed", f"Offer decision: {_friendly(status, 'Recorded')}", "Approval"
        if "sent" in status:
            return "Offer sent", "An offer-send record exists for this deal.", "Offer"
        return "Offer prepared", f"Offer status: {_friendly(status, 'Recorded')}", "Offer"
    if entity == "documents":
        name = _text(record.get("name") or record.get("document_type")) or "Deal document"
        if status in {"internal_review_ready", "needs_owner_approval", "owner_approval_required"}:
            return "Approval requested", f"{name} is waiting for review.", "Approval"
        if status in {"owner_approved", "owner_rejected"}:
            return "Approval completed", f"{name}: {_friendly(status, 'Recorded')}", "Approval"
        if "signed" in status:
            return "Contract signed", name, "Document"
        if "contract" in _text(record.get("document_type")).casefold() or "contract" in name.casefold():
            return "Contract created", name, "Document"
        return "Document added", name, "Document"
    if entity == "transactions":
        title = "Closing / transaction event"
        detail = _friendly(record.get("transaction_type"), "Transaction")
        if status:
            detail += f" · {_friendly(status, 'Recorded')}"
        return title, detail, "Closing"
    return "Deal record updated", "A linked deal record was updated.", "Deal"


def _event_key(entity: str, record: dict[str, Any], timestamp: datetime | None, title: str, detail: str) -> str:
    record_id = _text(record.get("id") or record.get("external_id"))
    if record_id:
        return f"{entity}:{record_id}"
    fingerprint = f"{entity}|{timestamp.isoformat() if timestamp else ''}|{title}|{detail}"
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def build_deal_timeline(
    deal: dict[str, Any],
    related: dict[str, list[dict[str, Any]]],
) -> tuple[DealTimelineEvent, ...]:
    """Build one deduplicated timeline without changing source records."""
    candidates: list[tuple[str, dict[str, Any]]] = []
    if _timestamp(deal) is not None:
        candidates.append(("deals", deal))
    for entity in ("activities", "communications", "tasks", "offers", "documents", "transactions"):
        candidates.extend((entity, record) for record in related.get(entity, []) if isinstance(record, dict))

    events: dict[str, DealTimelineEvent] = {}
    for entity, record in candidates:
        timestamp = _timestamp(record)
        if entity == "deals":
            title, detail, category = "Deal created", "The deal was added to CommandCore.", "Deal"
        else:
            title, detail, category = _event_text(entity, record)
        key = _event_key(entity, record, timestamp, title, detail)
        events.setdefault(
            key,
            DealTimelineEvent(
                event_key=key,
                occurred_at=timestamp,
                occurred_at_label=_date_label(timestamp),
                title=title,
                detail=detail,
                category=category,
                source_entity=entity,
                source_record_id=_text(record.get("id") or record.get("external_id")),
            ),
        )
    maximum = datetime.max.replace(tzinfo=UTC)
    return tuple(sorted(events.values(), key=lambda event: (event.occurred_at is None, event.occurred_at or maximum, event.event_key)))


def build_deal_next_action(
    deal: dict[str, Any],
    related: dict[str, list[dict[str, Any]]],
) -> DealNextAction:
    """Recommend from recorded approvals and tasks without executing anything."""
    stage = _friendly(deal.get("stage"), "Stage not recorded")
    owner = _text(deal.get("assigned_to") or deal.get("assigned_worker")) or "Not assigned"
    approvals = build_deal_approval_status(related.get("offers", []), related.get("documents", []))
    pending: DealApprovalStatus | None = next((item for item in approvals if item.actionable), None)
    if pending:
        return DealNextAction(
            current_stage=stage,
            waiting_for=pending.state,
            recommended_action=pending.next_step,
            responsible_person="Shawn or Sabrina",
            due_date="No due date recorded",
            blocker="Owner approval is required before this work can continue.",
            approval_needed=True,
        )

    task = next_open_task(related.get("tasks", []))
    if task:
        blocker = _text(task.get("blocker") or task.get("blocked_reason"))
        if not blocker and _text(task.get("status")).casefold() == "blocked":
            blocker = "This task is marked blocked; no reason was recorded."
        return DealNextAction(
            current_stage=stage,
            waiting_for=_friendly(task.get("status"), "Open task"),
            recommended_action=_text(task.get("title")) or "Review the next open task.",
            responsible_person=_text(task.get("assigned_to") or task.get("assigned_worker")) or owner,
            due_date=_text(task.get("due_at") or task.get("due_date")) or "No due date recorded",
            blocker=blocker or "No blocker recorded",
            approval_needed=False,
        )

    return DealNextAction(
        current_stage=stage,
        waiting_for="No open task recorded",
        recommended_action=f"Review the recorded {stage} stage and choose the next existing workflow.",
        responsible_person=owner,
        due_date="No due date recorded",
        blocker="No blocker recorded",
        approval_needed=False,
    )
