from datetime import UTC, datetime, timedelta

from cfh_disposition.campaign_cadence import (
    CadenceAction,
    CadencePriority,
    CadenceQueueItem,
    CampaignCadenceLedger,
    CampaignRefreshTask,
    RefreshTaskStatus,
)
from cfh_disposition.executive_cadence import cadence_action_items
from cfh_disposition.executive_command import (
    ExecutiveLane,
    ExecutivePriority,
)

NOW = datetime(2026, 8, 5, 21, 30, tzinfo=UTC)


def queue_item(**overrides) -> CadenceQueueItem:
    values = {
        "property_id": "property_123",
        "property_address": "101 Test Street, Bristol, VA, 24201",
        "property_updated_at": NOW - timedelta(days=1),
        "property_status": "Marketing Live",
        "channel_key": "email",
        "channel_name": "Matched Buyer Email",
        "channel_mode": "Approval Required",
        "launch_status": "Posted",
        "cadence_days": 14,
        "warning_days": 3,
        "last_activity_at": NOW - timedelta(days=16),
        "due_at": NOW - timedelta(days=2),
        "days_overdue": 2,
        "priority": CadencePriority.OVERDUE,
        "action": CadenceAction.REFRESH,
        "reason": "The email lane is beyond the saved internal cadence.",
        "instruction": "Prepare a fresh matched-buyer email through the consent-controlled workflow.",
        "owner": "Sabrina",
        "manager_approval_required": True,
        "clicks_7": 0,
        "clicks_30": 3,
        "registrations": 1,
        "applications": 0,
        "contracts": 0,
        "open_task_id": "",
    }
    values.update(overrides)
    return CadenceQueueItem(**values)


def test_approval_required_lane_routes_to_management() -> None:
    item = cadence_action_items(
        [queue_item()],
        CampaignCadenceLedger(),
        now=NOW,
    )[0]

    assert item.priority == ExecutivePriority.URGENT
    assert item.lane == ExecutiveLane.MANAGEMENT
    assert item.manager_only is True
    assert item.source == "15-Channel Campaign Cadence"
    assert item.page_name == "15-Channel Campaign Cadence & Refresh Center"
    assert "Approve" in item.action


def test_assisted_channel_routes_to_team_execution() -> None:
    row = queue_item(
        channel_key="facebook_groups",
        channel_name="Facebook Groups",
        channel_mode="Assisted Posting",
        manager_approval_required=False,
    )

    item = cadence_action_items([row], CampaignCadenceLedger(), now=NOW)[0]

    assert item.lane == ExecutiveLane.TEAM
    assert item.manager_only is False
    assert item.action == row.instruction


def test_blocked_failed_lane_stays_blocked_in_executive_queue() -> None:
    row = queue_item(
        priority=CadencePriority.BLOCKED,
        action=CadenceAction.REPAIR_FAILED,
        reason="The channel has a failed refresh record.",
        manager_approval_required=False,
    )

    item = cadence_action_items([row], CampaignCadenceLedger(), now=NOW)[0]

    assert item.priority == ExecutivePriority.BLOCKED
    assert item.lane == ExecutiveLane.TEAM
    assert "Repair Failed Channel" in item.title


def test_approved_open_task_moves_from_management_to_team() -> None:
    task = CampaignRefreshTask(
        task_id="task_123",
        batch_id="batch_123",
        property_id="property_123",
        property_address="101 Test Street, Bristol, VA, 24201",
        property_updated_at=NOW - timedelta(days=1),
        channel_key="email",
        channel_name="Matched Buyer Email",
        campaign="cadence_batch_email",
        action=CadenceAction.REFRESH,
        priority=CadencePriority.OVERDUE,
        status=RefreshTaskStatus.APPROVED,
        owner="Marketing Team",
        due_at=NOW,
        manager_approval_required=True,
        approved_by="Sabrina",
        approved_at=NOW - timedelta(minutes=30),
        reason="Email refresh is overdue.",
        instruction="Prepare and dispatch the approved email package.",
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(minutes=30),
    )
    row = queue_item(open_task_id=task.task_id)

    item = cadence_action_items(
        [row],
        CampaignCadenceLedger(tasks=[task]),
        now=NOW,
    )[0]

    assert item.lane == ExecutiveLane.TEAM
    assert item.manager_only is False
    assert item.owner == "Marketing Team"
    assert "Approved" in item.reason
    assert item.entity_id == task.task_id


def test_current_and_inactive_lanes_are_not_executive_actions() -> None:
    rows = [
        queue_item(priority=CadencePriority.CURRENT, action=CadenceAction.KEEP),
        queue_item(
            channel_key="blog",
            channel_name="Owner-Finance Blog",
            priority=CadencePriority.INACTIVE,
            action=CadenceAction.NOT_ACTIVE,
        ),
    ]

    assert cadence_action_items(rows, CampaignCadenceLedger(), now=NOW) == []
