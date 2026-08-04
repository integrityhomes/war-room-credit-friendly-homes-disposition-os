from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .facebook_groups import (
    FacebookGroupLedger,
    FacebookGroupPostStatus,
    active_groups,
    facebook_group_post_status,
)


@dataclass(frozen=True, slots=True)
class FacebookGroupQueueItem:
    group_id: str
    group_name: str
    group_url: str
    cooldown_days: int
    eligible: bool
    next_eligible_at: datetime | None
    wait_days: int
    message: str


def build_facebook_group_queue(
    ledger: FacebookGroupLedger,
    *,
    property_id: UUID | str,
    now: datetime | None = None,
) -> list[FacebookGroupQueueItem]:
    rows: list[FacebookGroupQueueItem] = []
    for group in active_groups(ledger):
        status: FacebookGroupPostStatus = facebook_group_post_status(
            ledger,
            property_id=property_id,
            group_id=group.group_id,
            now=now,
        )
        rows.append(
            FacebookGroupQueueItem(
                group_id=group.group_id,
                group_name=group.name,
                group_url=group.group_url,
                cooldown_days=group.cooldown_days,
                eligible=status.eligible,
                next_eligible_at=status.next_eligible_at,
                wait_days=status.wait_days,
                message=status.message,
            )
        )
    return rows


def queue_summary_rows(
    queue: list[FacebookGroupQueueItem],
) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for item in queue:
        rows.append(
            {
                "Facebook Group": item.group_name,
                "Ready Now": "Yes" if item.eligible else "No",
                "Cooldown Days": item.cooldown_days,
                "Wait Days": item.wait_days,
                "Next Eligible": (
                    item.next_eligible_at.strftime("%Y-%m-%d %I:%M %p ET")
                    if item.next_eligible_at
                    else "Now"
                ),
                "Status": item.message,
            }
        )
    return rows


def eligible_queue_items(
    queue: list[FacebookGroupQueueItem],
) -> list[FacebookGroupQueueItem]:
    return [item for item in queue if item.eligible]
