from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .commandcore_contract_controls import pending_document

TERMINAL_STATUSES = {
    "cancelled",
    "canceled",
    "closed",
    "completed",
    "done",
    "owner_rejected",
}


@dataclass(frozen=True, slots=True)
class DealAtAGlance:
    next_task: dict[str, Any] | None
    recent_communication: dict[str, Any] | None
    recent_activity: dict[str, Any] | None
    offer: dict[str, Any] | None
    document: dict[str, Any] | None
    closing: dict[str, Any] | None
    marketing: dict[str, Any] | None
    approval_count: int


def text(value: Any) -> str:
    return str(value or "").strip()


def status_label(record: dict[str, Any] | None, *, empty: str = "Not started") -> str:
    if record is None:
        return empty
    status = text(record.get("status"))
    return status.replace("_", " ").replace("-", " ").title() if status else "Status not recorded"


def _timestamp(value: Any) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.fromisoformat(raw[:10])
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _record_timestamp(record: dict[str, Any], fields: tuple[str, ...]) -> datetime | None:
    for field in fields:
        parsed = _timestamp(record.get(field))
        if parsed is not None:
            return parsed
    return None


def latest_record(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    minimum = datetime.min.replace(tzinfo=UTC)
    return max(
        enumerate(rows),
        key=lambda item: (
            _record_timestamp(
                item[1],
                ("updated_at", "created_at", "occurred_at", "requested_at", "timestamp"),
            )
            or minimum,
            item[0],
        ),
    )[1]


def next_open_task(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    open_rows = [row for row in rows if text(row.get("status")).casefold() not in TERMINAL_STATUSES]
    if not open_rows:
        return None
    maximum = datetime.max.replace(tzinfo=UTC)
    return min(
        enumerate(open_rows),
        key=lambda item: (
            _record_timestamp(item[1], ("due_at", "due_date")) is None,
            _record_timestamp(item[1], ("due_at", "due_date")) or maximum,
            item[0],
        ),
    )[1]


def _work_record(rows: list[dict[str, Any]], work_type: str) -> dict[str, Any] | None:
    return latest_record([row for row in rows if text(row.get("work_type")) == work_type])


def build_deal_summary(related: dict[str, list[dict[str, Any]]]) -> DealAtAGlance:
    tasks = related.get("tasks", [])
    offers = related.get("offers", [])
    documents = related.get("documents", [])
    transactions = related.get("transactions", [])
    closing = latest_record(transactions) or _work_record(tasks, "title_closing")

    return DealAtAGlance(
        next_task=next_open_task(tasks),
        recent_communication=latest_record(related.get("communications", [])),
        recent_activity=latest_record(related.get("activities", [])),
        offer=latest_record(offers),
        document=latest_record(documents),
        closing=closing,
        marketing=_work_record(tasks, "marketing_dispo"),
        approval_count=sum(
            text(offer.get("status")).casefold() == "draft_pending_owner_approval"
            for offer in offers
        )
        + sum(pending_document(document) for document in documents),
    )
