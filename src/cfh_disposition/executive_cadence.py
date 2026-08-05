from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from .campaign_cadence import (
    CadencePriority,
    CadenceQueueItem,
    CampaignCadenceLedger,
    RefreshTaskStatus,
)
from .executive_command import (
    ExecutiveActionItem,
    ExecutiveLane,
    ExecutivePriority,
)


PRIORITY_MAP = {
    CadencePriority.BLOCKED: ExecutivePriority.BLOCKED,
    CadencePriority.OVERDUE: ExecutivePriority.URGENT,
    CadencePriority.DUE_NOW: ExecutivePriority.HIGH,
    CadencePriority.DUE_SOON: ExecutivePriority.WATCH,
    CadencePriority.CURRENT: ExecutivePriority.NORMAL,
    CadencePriority.INACTIVE: ExecutivePriority.WATCH,
}


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def cadence_action_items(
    queue: Sequence[CadenceQueueItem],
    ledger: CampaignCadenceLedger,
    *,
    now: datetime | None = None,
) -> list[ExecutiveActionItem]:
    current = _current(now)
    tasks_by_id = {task.task_id: task for task in ledger.tasks}
    items: list[ExecutiveActionItem] = []

    for row in queue:
        if row.priority in {CadencePriority.CURRENT, CadencePriority.INACTIVE}:
            continue
        task = tasks_by_id.get(row.open_task_id) if row.open_task_id else None
        approval_waiting = row.manager_approval_required and (
            task is None
            or (
                task.status in {RefreshTaskStatus.READY, RefreshTaskStatus.FAILED}
                and task.approved_at is None
            )
        )
        lane = ExecutiveLane.MANAGEMENT if approval_waiting else ExecutiveLane.TEAM
        owner = task.owner if task else row.owner
        due_at = task.due_at if task else row.due_at or current
        action = (
            "Approve the current fact-safe channel package, then assign the refresh."
            if approval_waiting
            else row.instruction
        )
        status_detail = f" Open task status: {task.status.value}." if task else ""
        items.append(
            ExecutiveActionItem(
                action_id=f"campaign-cadence:{row.property_id}:{row.channel_key}",
                priority=PRIORITY_MAP[row.priority],
                lane=lane,
                source="15-Channel Campaign Cadence",
                title=f"{row.action.value} — {row.channel_name} — {row.property_address}",
                action=action,
                reason=row.reason + status_detail,
                owner=owner,
                due_at=due_at,
                property_id=row.property_id,
                property_address=row.property_address,
                manager_only=approval_waiting,
                page_name="15-Channel Campaign Cadence & Refresh Center",
                entity_id=(task.task_id if task else f"{row.property_id}:{row.channel_key}"),
            )
        )
    return items
