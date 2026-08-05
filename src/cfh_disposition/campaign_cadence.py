from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ai_campaign import build_fallback_campaign
from .analytics import ClickEvent
from .automatic_launch import (
    AutomationDispatchReceipt,
    AutomationDispatchSettings,
    LaunchAction,
    channel_copy_with_link,
    launch_action_for_channel,
    serialize_launch_payload,
    sign_launch_payload,
)
from .campaign_launch import CampaignLaunchState, LaunchStatus, ensure_all_channels
from .channel_tracking import build_channel_links, canonical_channel_key
from .channels import CHANNELS, CHANNELS_BY_KEY, ChannelMode
from .dwelyx_attribution import (
    STAGE_RANK,
    DwelyxAttributionEvent,
    JourneyStage,
    build_journeys,
)
from .models import OwnerFinanceProperty, PropertyStatus
from .nextdoor import build_nextdoor_package
from .storage import SupabaseSettings

CADENCE_BUCKET = "cfh-campaign-cadence"
CADENCE_PATH = "campaign-cadence/ledger.json"
CADENCE_MAX_BYTES = 5 * 1024 * 1024
CADENCE_EVENT = "credit_friendly_homes.campaign.refresh"
CADENCE_SCHEMA_VERSION = "1.0"
CADENCE_RESPONSE_LIMIT = 500
ACTIVE_PROPERTY_STATUSES = {PropertyStatus.READY, PropertyStatus.LIVE}

DEFAULT_CADENCE_DAYS: dict[str, int] = {
    "property_page": 7,
    "blog": 30,
    "market_seo": 14,
    "email": 14,
    "sms": 14,
    "reactivation": 30,
    "marketplace": 14,
    "facebook_groups": 7,
    "meta_ads": 7,
    "google_ads": 7,
    "instagram": 7,
    "tiktok": 7,
    "youtube": 14,
    "classifieds": 14,
    "nextdoor": 14,
}

DEFAULT_OWNER_BY_CHANNEL: dict[str, str] = {
    "property_page": "Sabrina",
    "blog": "Marketing Team",
    "market_seo": "Marketing Team",
    "email": "Sabrina",
    "sms": "Sabrina",
    "reactivation": "Sabrina",
    "marketplace": "Posting Team",
    "facebook_groups": "Posting Team",
    "meta_ads": "Sabrina",
    "google_ads": "Sabrina",
    "instagram": "Marketing Team",
    "tiktok": "Marketing Team",
    "youtube": "Marketing Team",
    "classifieds": "Posting Team",
    "nextdoor": "Posting Team",
}


class CampaignCadenceError(RuntimeError):
    """Raised when the campaign cadence workflow cannot complete safely."""


class CadencePriority(StrEnum):
    BLOCKED = "Blocked"
    OVERDUE = "Overdue"
    DUE_NOW = "Due Now"
    DUE_SOON = "Due Soon"
    CURRENT = "Current"
    INACTIVE = "Inactive"


class CadenceAction(StrEnum):
    PROTECT_CONTRACT = "Protect Signed Contract"
    REPAIR_FAILED = "Repair Failed Channel"
    LAUNCH_MISSING = "Launch Missing Channel"
    REFRESH = "Refresh Current Campaign"
    VERIFY = "Verify Current Placement"
    KEEP = "Keep Current"
    NOT_ACTIVE = "No Active Marketing"


class RefreshTaskStatus(StrEnum):
    READY = "Ready"
    APPROVED = "Approved"
    IN_PROGRESS = "In Progress"
    DISPATCHED = "Dispatched"
    CONFIRMED = "Confirmed"
    SKIPPED = "Skipped"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


OPEN_TASK_STATUSES = {
    RefreshTaskStatus.READY,
    RefreshTaskStatus.APPROVED,
    RefreshTaskStatus.IN_PROGRESS,
    RefreshTaskStatus.DISPATCHED,
    RefreshTaskStatus.FAILED,
}

CLOSED_TASK_STATUSES = {
    RefreshTaskStatus.CONFIRMED,
    RefreshTaskStatus.SKIPPED,
    RefreshTaskStatus.CANCELLED,
}

PRIORITY_SORT = {
    CadencePriority.BLOCKED: 0,
    CadencePriority.OVERDUE: 1,
    CadencePriority.DUE_NOW: 2,
    CadencePriority.DUE_SOON: 3,
    CadencePriority.CURRENT: 4,
    CadencePriority.INACTIVE: 5,
}


class ChannelCadencePolicy(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    channel_key: str
    cadence_days: int = Field(ge=1, le=365)
    warning_days: int = Field(default=2, ge=0, le=90)
    enabled: bool = True
    default_owner: str = Field(default="Marketing Team", max_length=120)
    notes: str = Field(default="", max_length=2000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("channel_key")
    @classmethod
    def validate_channel_key(cls, value: str) -> str:
        if value not in CHANNELS_BY_KEY:
            raise ValueError("Unknown marketing channel")
        return value

    @model_validator(mode="after")
    def validate_warning_window(self) -> ChannelCadencePolicy:
        if self.warning_days >= self.cadence_days:
            raise ValueError("Warning days must be less than cadence days")
        return self


class CampaignRefreshTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    batch_id: str
    property_id: str
    property_address: str = Field(min_length=2, max_length=320)
    property_updated_at: datetime
    channel_key: str
    channel_name: str
    campaign: str = Field(min_length=3, max_length=180)
    action: CadenceAction
    priority: CadencePriority
    status: RefreshTaskStatus = RefreshTaskStatus.READY
    owner: str = Field(default="Marketing Team", max_length=120)
    due_at: datetime
    last_activity_at: datetime | None = None
    manager_approval_required: bool = False
    approved_by: str = Field(default="", max_length=120)
    approved_at: datetime | None = None
    completed_by: str = Field(default="", max_length=120)
    completed_at: datetime | None = None
    reason: str = Field(min_length=5, max_length=1800)
    instruction: str = Field(min_length=5, max_length=1800)
    dispatch_detail: str = Field(default="", max_length=1500)
    notes: str = Field(default="", max_length=2500)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("channel_key")
    @classmethod
    def validate_channel_key(cls, value: str) -> str:
        if value not in CHANNELS_BY_KEY:
            raise ValueError("Unknown marketing channel")
        return value


class CampaignCadenceLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    policies: list[ChannelCadencePolicy] = Field(default_factory=list)
    tasks: list[CampaignRefreshTask] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CadenceQueueItem:
    property_id: str
    property_address: str
    property_updated_at: datetime
    property_status: str
    channel_key: str
    channel_name: str
    channel_mode: str
    launch_status: str
    cadence_days: int
    warning_days: int
    last_activity_at: datetime | None
    due_at: datetime | None
    days_overdue: int
    priority: CadencePriority
    action: CadenceAction
    reason: str
    instruction: str
    owner: str
    manager_approval_required: bool
    clicks_7: int
    clicks_30: int
    registrations: int
    applications: int
    contracts: int
    open_task_id: str


@dataclass(frozen=True, slots=True)
class CadenceSnapshot:
    total_active_lanes: int
    blocked: int
    overdue: int
    due_now: int
    due_soon: int
    current: int
    open_tasks: int
    coverage_rate: float


@dataclass(frozen=True, slots=True)
class RefreshMaterials:
    tracked_link: str
    copy: str
    launch_action: LaunchAction
    requires_manual_final_post: bool


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _default_instruction(channel_key: str) -> str:
    instructions = {
        "property_page": "Verify the public property page still displays the current approved facts, photos, availability, and Dwelyx destination.",
        "blog": "Review the owner-finance article or property feature, update stale facts, and publish only after content approval.",
        "market_seo": "Verify the city and market inventory page reflects the current property and links correctly to Dwelyx.",
        "email": "Prepare a fresh matched-buyer email and send only through the consent-controlled workflow after approval.",
        "sms": "Prepare a concise matched-buyer SMS and send only to buyers with current SMS consent and cooldown eligibility.",
        "reactivation": "Prepare a referral or reactivation sequence and recheck consent, cooldown, and engagement stops before dispatch.",
        "marketplace": "Review the existing For Sale listing. Do not create a duplicate listing or bypass the monthly Marketplace safety counter.",
        "facebook_groups": "Use the Facebook Group Posting Center, current group-specific cooldowns, and a fresh approved variation before confirming the post.",
        "meta_ads": "Review the housing-ad creative, destination, results, and approved budget. Do not change spend without management approval.",
        "google_ads": "Review search terms, ad copy, destination, results, and approved budget. Do not change spend without management approval.",
        "instagram": "Prepare a fresh Reel or post using current property facts and the tracked Dwelyx destination.",
        "tiktok": "Prepare a fresh short-form video package using current property facts and the tracked Dwelyx destination.",
        "youtube": "Prepare or refresh the YouTube Short using current property facts and the tracked Dwelyx destination.",
        "classifieds": "Review each active classified placement, refresh only where allowed, and confirm the exact posting location.",
        "nextdoor": "Prepare the current Nextdoor Business Post and housing-ad package. Final publication, targeting, and spending remain manual and approval-controlled.",
    }
    return instructions[channel_key]


def default_cadence_policies(now: datetime | None = None) -> list[ChannelCadencePolicy]:
    current = _current(now)
    return [
        ChannelCadencePolicy(
            channel_key=channel.key,
            cadence_days=DEFAULT_CADENCE_DAYS[channel.key],
            warning_days=min(3, max(1, DEFAULT_CADENCE_DAYS[channel.key] // 4)),
            enabled=True,
            default_owner=DEFAULT_OWNER_BY_CHANNEL[channel.key],
            notes="Internal Credit Friendly Homes operating cadence; not a platform rule.",
            updated_at=current,
        )
        for channel in CHANNELS
    ]


def ensure_all_policies(
    ledger: CampaignCadenceLedger,
    *,
    now: datetime | None = None,
) -> CampaignCadenceLedger:
    current = _current(now)
    saved = {policy.channel_key: policy for policy in ledger.policies if policy.channel_key in CHANNELS_BY_KEY}
    defaults = {policy.channel_key: policy for policy in default_cadence_policies(current)}
    policies = [saved.get(channel.key, defaults[channel.key]) for channel in CHANNELS]
    return ledger.model_copy(update={"policies": policies})


def policy_for_channel(
    ledger: CampaignCadenceLedger,
    channel_key: str,
) -> ChannelCadencePolicy:
    normalized = ensure_all_policies(ledger)
    return next(policy for policy in normalized.policies if policy.channel_key == channel_key)


def upsert_policy(
    ledger: CampaignCadenceLedger,
    policy: ChannelCadencePolicy,
    *,
    now: datetime | None = None,
) -> CampaignCadenceLedger:
    current = _current(now)
    updated_policy = policy.model_copy(update={"updated_at": current})
    normalized = ensure_all_policies(ledger, now=current)
    policies = [
        updated_policy if item.channel_key == updated_policy.channel_key else item
        for item in normalized.policies
    ]
    return normalized.model_copy(update={"policies": policies, "updated_at": current})


def _latest_confirmed_task(
    ledger: CampaignCadenceLedger,
    property_id: str,
    channel_key: str,
) -> CampaignRefreshTask | None:
    completed = [
        task
        for task in ledger.tasks
        if task.property_id == property_id
        and task.channel_key == channel_key
        and task.status == RefreshTaskStatus.CONFIRMED
        and task.completed_at is not None
    ]
    return max(completed, key=lambda item: item.completed_at or item.updated_at, default=None)


def _open_task(
    ledger: CampaignCadenceLedger,
    property_id: str,
    channel_key: str,
) -> CampaignRefreshTask | None:
    open_tasks = [
        task
        for task in ledger.tasks
        if task.property_id == property_id
        and task.channel_key == channel_key
        and task.status in OPEN_TASK_STATUSES
    ]
    return max(open_tasks, key=lambda item: item.updated_at, default=None)


def _launch_record(
    launch_state: CampaignLaunchState | None,
    channel_key: str,
):
    if launch_state is None:
        return None
    return ensure_all_channels(launch_state).channels.get(channel_key)


def _latest_activity(
    property_record: OwnerFinanceProperty,
    ledger: CampaignCadenceLedger,
    launch_state: CampaignLaunchState | None,
    channel_key: str,
) -> datetime | None:
    candidates: list[datetime] = []
    record = _launch_record(launch_state, channel_key)
    if record and record.updated_at:
        candidates.append(_as_utc(record.updated_at))
    completed = _latest_confirmed_task(ledger, str(property_record.property_id), channel_key)
    if completed and completed.completed_at:
        candidates.append(_as_utc(completed.completed_at))
    if channel_key == "property_page":
        candidates.append(_as_utc(property_record.updated_at))
    return max(candidates, default=None)


def _click_counts(
    events: Sequence[ClickEvent],
    *,
    property_id: str,
    channel_key: str,
    now: datetime,
) -> tuple[int, int]:
    relevant = [
        event
        for event in events
        if event.property_id == property_id
        and canonical_channel_key(event.medium) == channel_key
        and event.occurred_at <= now
    ]
    clicks_7 = sum(event.occurred_at >= now - timedelta(days=7) for event in relevant)
    clicks_30 = sum(event.occurred_at >= now - timedelta(days=30) for event in relevant)
    return clicks_7, clicks_30


def _journey_metrics(
    events: Sequence[DwelyxAttributionEvent],
) -> dict[tuple[str, str], tuple[int, int, int]]:
    grouped: dict[tuple[str, str], list[DwelyxAttributionEvent]] = defaultdict(list)
    for event in events:
        if event.test_mode or not event.cfh_property_id:
            continue
        grouped[(event.cfh_property_id, event.channel_key)].append(event)

    metrics: dict[tuple[str, str], tuple[int, int, int]] = {}
    for key, grouped_events in grouped.items():
        journeys = build_journeys(grouped_events)
        registrations = sum(
            STAGE_RANK[journey.stage] >= STAGE_RANK[JourneyStage.REGISTERED]
            for journey in journeys
        )
        applications = sum(
            STAGE_RANK[journey.stage] >= STAGE_RANK[JourneyStage.APPLICATION_SUBMITTED]
            for journey in journeys
        )
        contracts = sum(
            STAGE_RANK[journey.stage] >= STAGE_RANK[JourneyStage.CONTRACT_SIGNED]
            for journey in journeys
        )
        metrics[key] = (registrations, applications, contracts)
    return metrics


def _property_contract_count(
    metrics: Mapping[tuple[str, str], tuple[int, int, int]],
    property_id: str,
) -> int:
    return sum(values[2] for (saved_property_id, _), values in metrics.items() if saved_property_id == property_id)


def _manager_approval_required(channel_key: str) -> bool:
    channel = CHANNELS_BY_KEY[channel_key]
    return channel.mode == ChannelMode.APPROVAL_REQUIRED or channel_key == "nextdoor"


def _inactive_queue_item(
    property_record: OwnerFinanceProperty,
    policy: ChannelCadencePolicy,
    channel_key: str,
) -> CadenceQueueItem:
    channel = CHANNELS_BY_KEY[channel_key]
    return CadenceQueueItem(
        property_id=str(property_record.property_id),
        property_address=property_record.display_address,
        property_updated_at=_as_utc(property_record.updated_at),
        property_status=property_record.status.value,
        channel_key=channel_key,
        channel_name=channel.name,
        channel_mode=channel.mode.value,
        launch_status="Inactive",
        cadence_days=policy.cadence_days,
        warning_days=policy.warning_days,
        last_activity_at=None,
        due_at=None,
        days_overdue=0,
        priority=CadencePriority.INACTIVE,
        action=CadenceAction.NOT_ACTIVE,
        reason="The property is not currently Ready to Launch or Marketing Live.",
        instruction="Do not refresh this channel until the property returns to active marketing status.",
        owner=policy.default_owner,
        manager_approval_required=False,
        clicks_7=0,
        clicks_30=0,
        registrations=0,
        applications=0,
        contracts=0,
        open_task_id="",
    )


def build_cadence_queue(
    properties: Sequence[OwnerFinanceProperty],
    *,
    ledger: CampaignCadenceLedger,
    launch_states: Mapping[str, CampaignLaunchState | None] | None = None,
    click_events: Sequence[ClickEvent] = (),
    attribution_events: Sequence[DwelyxAttributionEvent] = (),
    now: datetime | None = None,
) -> list[CadenceQueueItem]:
    current = _current(now)
    normalized = ensure_all_policies(ledger, now=current)
    policies = {policy.channel_key: policy for policy in normalized.policies}
    states = launch_states or {}
    journey_metrics = _journey_metrics(attribution_events)
    rows: list[CadenceQueueItem] = []

    for property_record in properties:
        property_id = str(property_record.property_id)
        active_property = property_record.status in ACTIVE_PROPERTY_STATUSES
        property_contracts = _property_contract_count(journey_metrics, property_id)
        launch_state = states.get(property_id)

        for channel in CHANNELS:
            policy = policies[channel.key]
            if not active_property or not policy.enabled:
                rows.append(_inactive_queue_item(property_record, policy, channel.key))
                continue

            launch_record = _launch_record(launch_state, channel.key)
            launch_status = launch_record.status if launch_record else LaunchStatus.NOT_STARTED
            last_activity = _latest_activity(
                property_record,
                normalized,
                launch_state,
                channel.key,
            )
            clicks_7, clicks_30 = _click_counts(
                click_events,
                property_id=property_id,
                channel_key=channel.key,
                now=current,
            )
            registrations, applications, channel_contracts = journey_metrics.get(
                (property_id, channel.key),
                (0, 0, 0),
            )
            open_task = _open_task(normalized, property_id, channel.key)
            due_at = (
                last_activity + timedelta(days=policy.cadence_days)
                if last_activity
                else current
            )
            days_overdue = max(
                0,
                int((current - due_at).total_seconds() // 86400) + (1 if current > due_at else 0),
            )
            manager_required = _manager_approval_required(channel.key)
            instruction = _default_instruction(channel.key)

            if property_contracts > 0:
                priority = CadencePriority.BLOCKED
                action = CadenceAction.PROTECT_CONTRACT
                reason = (
                    "A signed-contract result exists for this property. Verify the property status and "
                    "shutdown timing before refreshing any channel."
                )
            elif launch_status == LaunchStatus.FAILED or (
                open_task and open_task.status == RefreshTaskStatus.FAILED
            ):
                priority = CadencePriority.BLOCKED
                action = CadenceAction.REPAIR_FAILED
                reason = "The channel has a failed launch or refresh record that must be repaired before another cycle."
            elif launch_status in {
                LaunchStatus.NOT_STARTED,
                LaunchStatus.READY,
            }:
                priority = CadencePriority.OVERDUE
                action = CadenceAction.LAUNCH_MISSING
                reason = "The property is active, but this channel is not recorded as Posted or Scheduled."
            elif launch_status == LaunchStatus.PAUSED:
                priority = CadencePriority.BLOCKED
                action = CadenceAction.REPAIR_FAILED
                reason = "This channel is paused while the property is still active. Confirm whether it should resume."
            elif open_task:
                priority = (
                    CadencePriority.BLOCKED
                    if open_task.status == RefreshTaskStatus.FAILED
                    else CadencePriority.DUE_NOW
                )
                action = open_task.action
                reason = f"An open refresh task is already {open_task.status.value}."
                due_at = open_task.due_at
                days_overdue = max(
                    0,
                    int((current - due_at).total_seconds() // 86400) + (1 if current > due_at else 0),
                )
            elif current > due_at:
                priority = CadencePriority.OVERDUE
                action = CadenceAction.REFRESH
                reason = f"This channel is {days_overdue} day(s) beyond the saved internal cadence."
            elif current >= due_at - timedelta(days=policy.warning_days):
                priority = CadencePriority.DUE_SOON
                action = CadenceAction.REFRESH
                reason = "This channel is inside its saved refresh warning window."
            else:
                priority = CadencePriority.CURRENT
                action = CadenceAction.KEEP
                reason = "This channel is inside the saved internal cadence window."

            if (
                priority == CadencePriority.CURRENT
                and property_record.status == PropertyStatus.LIVE
                and clicks_30 == 0
                and last_activity is not None
                and current - last_activity >= timedelta(days=max(3, policy.cadence_days // 2))
            ):
                priority = CadencePriority.DUE_NOW
                action = CadenceAction.VERIFY
                reason = (
                    "The placement is recorded as active but produced no tracked clicks in 30 days. "
                    "Verify the link and placement before simply reposting."
                )
                due_at = current

            rows.append(
                CadenceQueueItem(
                    property_id=property_id,
                    property_address=property_record.display_address,
                    property_updated_at=_as_utc(property_record.updated_at),
                    property_status=property_record.status.value,
                    channel_key=channel.key,
                    channel_name=channel.name,
                    channel_mode=channel.mode.value,
                    launch_status=launch_status.value,
                    cadence_days=policy.cadence_days,
                    warning_days=policy.warning_days,
                    last_activity_at=last_activity,
                    due_at=due_at,
                    days_overdue=days_overdue,
                    priority=priority,
                    action=action,
                    reason=reason,
                    instruction=instruction,
                    owner=policy.default_owner,
                    manager_approval_required=manager_required,
                    clicks_7=clicks_7,
                    clicks_30=clicks_30,
                    registrations=registrations,
                    applications=applications,
                    contracts=channel_contracts,
                    open_task_id=open_task.task_id if open_task else "",
                )
            )

    return sorted(
        rows,
        key=lambda item: (
            PRIORITY_SORT[item.priority],
            item.due_at or datetime.max.replace(tzinfo=UTC),
            item.property_address.casefold(),
            item.channel_name.casefold(),
        ),
    )


def cadence_snapshot(
    queue: Sequence[CadenceQueueItem],
    ledger: CampaignCadenceLedger,
) -> CadenceSnapshot:
    active = [item for item in queue if item.priority != CadencePriority.INACTIVE]
    current_count = sum(item.priority == CadencePriority.CURRENT for item in active)
    total_active = len(active)
    return CadenceSnapshot(
        total_active_lanes=total_active,
        blocked=sum(item.priority == CadencePriority.BLOCKED for item in active),
        overdue=sum(item.priority == CadencePriority.OVERDUE for item in active),
        due_now=sum(item.priority == CadencePriority.DUE_NOW for item in active),
        due_soon=sum(item.priority == CadencePriority.DUE_SOON for item in active),
        current=current_count,
        open_tasks=sum(task.status in OPEN_TASK_STATUSES for task in ledger.tasks),
        coverage_rate=(current_count / total_active if total_active else 0.0),
    )


def create_refresh_batch(
    ledger: CampaignCadenceLedger,
    items: Sequence[CadenceQueueItem],
    *,
    requested_by: str,
    now: datetime | None = None,
) -> tuple[CampaignCadenceLedger, list[CampaignRefreshTask]]:
    if not requested_by.strip():
        raise CampaignCadenceError("Enter the team member creating the refresh batch.")
    current = _current(now)
    batch_id = str(uuid4())
    created: list[CampaignRefreshTask] = []
    existing = {
        (task.property_id, task.channel_key)
        for task in ledger.tasks
        if task.status in OPEN_TASK_STATUSES
    }

    for item in items:
        if item.priority in {CadencePriority.CURRENT, CadencePriority.INACTIVE}:
            continue
        if item.action == CadenceAction.PROTECT_CONTRACT:
            continue
        key = (item.property_id, item.channel_key)
        if key in existing:
            continue
        task = CampaignRefreshTask(
            batch_id=batch_id,
            property_id=item.property_id,
            property_address=item.property_address,
            property_updated_at=item.property_updated_at,
            channel_key=item.channel_key,
            channel_name=item.channel_name,
            campaign=f"cadence_{batch_id[:8]}_{item.channel_key}",
            action=item.action,
            priority=item.priority,
            status=RefreshTaskStatus.READY,
            owner=item.owner,
            due_at=item.due_at or current,
            last_activity_at=item.last_activity_at,
            manager_approval_required=item.manager_approval_required,
            reason=item.reason,
            instruction=item.instruction,
            created_at=current,
            updated_at=current,
        )
        created.append(task)
        existing.add(key)

    if not created:
        raise CampaignCadenceError(
            "No new refresh tasks were created. The selected lanes are current, inactive, contract-protected, or already have open tasks."
        )
    return (
        ensure_all_policies(ledger, now=current).model_copy(
            update={"tasks": [*ledger.tasks, *created], "updated_at": current}
        ),
        created,
    )


def find_refresh_task(
    ledger: CampaignCadenceLedger,
    task_id: str,
) -> CampaignRefreshTask | None:
    return next((task for task in ledger.tasks if task.task_id == task_id), None)


def _replace_task(
    ledger: CampaignCadenceLedger,
    updated: CampaignRefreshTask,
    *,
    now: datetime | None = None,
) -> CampaignCadenceLedger:
    current = _current(now)
    tasks = [updated if task.task_id == updated.task_id else task for task in ledger.tasks]
    return ledger.model_copy(update={"tasks": tasks, "updated_at": current})


def _assert_property_fresh(
    task: CampaignRefreshTask,
    property_record: OwnerFinanceProperty,
) -> None:
    if str(property_record.property_id) != task.property_id:
        raise CampaignCadenceError("The selected refresh task does not belong to this property.")
    if property_record.status not in ACTIVE_PROPERTY_STATUSES:
        raise CampaignCadenceError("This property is no longer active for marketing.")
    if _as_utc(property_record.updated_at) != _as_utc(task.property_updated_at):
        raise CampaignCadenceError(
            "The property record changed after this refresh task was created. Cancel the stale task and generate a new package."
        )


def approve_refresh_task(
    ledger: CampaignCadenceLedger,
    property_record: OwnerFinanceProperty,
    *,
    task_id: str,
    approved_by: str,
    now: datetime | None = None,
) -> CampaignCadenceLedger:
    if not approved_by.strip():
        raise CampaignCadenceError("Enter the team member approving this refresh.")
    task = find_refresh_task(ledger, task_id)
    if task is None:
        raise CampaignCadenceError("The selected refresh task could not be found.")
    if task.status not in {RefreshTaskStatus.READY, RefreshTaskStatus.FAILED}:
        raise CampaignCadenceError("Only Ready or Failed refresh tasks can be approved.")
    _assert_property_fresh(task, property_record)
    current = _current(now)
    updated = task.model_copy(
        update={
            "status": RefreshTaskStatus.APPROVED,
            "approved_by": approved_by.strip(),
            "approved_at": current,
            "dispatch_detail": "",
            "updated_at": current,
        }
    )
    return _replace_task(ledger, updated, now=current)


def update_refresh_task(
    ledger: CampaignCadenceLedger,
    *,
    task_id: str,
    status: RefreshTaskStatus,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> CampaignCadenceLedger:
    if not actor.strip():
        raise CampaignCadenceError("Enter the team member updating this task.")
    task = find_refresh_task(ledger, task_id)
    if task is None:
        raise CampaignCadenceError("The selected refresh task could not be found.")
    if task.status in CLOSED_TASK_STATUSES:
        raise CampaignCadenceError("A closed refresh task cannot be changed.")
    if status == RefreshTaskStatus.CONFIRMED and task.manager_approval_required and not task.approved_at:
        raise CampaignCadenceError("Management approval is required before this channel can be confirmed refreshed.")
    current = _current(now)
    completed = status in CLOSED_TASK_STATUSES
    updated = task.model_copy(
        update={
            "status": status,
            "completed_by": actor.strip() if completed else task.completed_by,
            "completed_at": current if completed else task.completed_at,
            "notes": notes.strip(),
            "updated_at": current,
        }
    )
    return _replace_task(ledger, updated, now=current)


def build_refresh_materials(
    task: CampaignRefreshTask,
    property_record: OwnerFinanceProperty,
    dwelyx_url: str,
) -> RefreshMaterials:
    _assert_property_fresh(task, property_record)
    links = build_channel_links(
        dwelyx_url,
        campaign=task.campaign,
        property_id=property_record.property_id,
    )
    link_row = next(row for row in links if row["Channel key"] == task.channel_key)
    tracked_link = link_row["Tracked Dwelyx link"]
    channel = CHANNELS_BY_KEY[task.channel_key]
    launch_action = launch_action_for_channel(channel)

    if task.channel_key == "nextdoor":
        package = build_nextdoor_package(property_record, tracked_link)
        copy = (
            f"BUSINESS POST\n{package.business_post_title}\n\n{package.business_post_body}\n\n"
            f"PAID HOUSING AD\n{package.paid_ad_headline}\n\n{package.paid_ad_body}\n\n"
            f"Call to action: {package.paid_ad_cta}"
        )
    else:
        package = build_fallback_campaign(property_record, tracked_link)
        copy = channel_copy_with_link(package, task.channel_key, tracked_link)

    return RefreshMaterials(
        tracked_link=tracked_link,
        copy=copy,
        launch_action=launch_action,
        requires_manual_final_post=launch_action == LaunchAction.MANUAL_FINAL_POST,
    )


def build_refresh_payload(
    task: CampaignRefreshTask,
    property_record: OwnerFinanceProperty,
    materials: RefreshMaterials,
    *,
    requested_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _assert_property_fresh(task, property_record)
    if task.manager_approval_required and task.status not in {
        RefreshTaskStatus.APPROVED,
        RefreshTaskStatus.IN_PROGRESS,
        RefreshTaskStatus.DISPATCHED,
    }:
        raise CampaignCadenceError("This refresh requires management approval before dispatch.")
    current = _current(now)
    return {
        "schema_version": CADENCE_SCHEMA_VERSION,
        "event": CADENCE_EVENT,
        "requested_at": current.isoformat(),
        "requested_by": requested_by,
        "task_id": task.task_id,
        "batch_id": task.batch_id,
        "campaign": task.campaign,
        "action": task.action.value,
        "property": {
            "property_id": task.property_id,
            "address": property_record.address,
            "city": property_record.city,
            "state": property_record.state,
            "zip_code": property_record.zip_code,
            "down_payment": str(property_record.down_payment) if property_record.down_payment is not None else None,
            "monthly_payment": str(property_record.monthly_payment) if property_record.monthly_payment is not None else None,
            "condition_summary": property_record.condition_summary,
            "repairs_needed": property_record.repairs_needed,
            "public_disclosures": property_record.public_disclosures,
            "photo_urls": [str(url) for url in property_record.photo_urls],
        },
        "channel": {
            "channel_key": task.channel_key,
            "channel_name": task.channel_name,
            "launch_action": materials.launch_action.value,
            "requires_manual_final_post": materials.requires_manual_final_post,
            "tracked_buyer_link": None if task.channel_key == "marketplace" else materials.tracked_link,
            "copy": materials.copy,
        },
        "buyer_destination": {
            "purpose": "Dwelyx buyer registration or login only",
            "publish_property_to_dwelyx": False,
            "property_sync_to_dwelyx": False,
        },
        "controls": {
            "change_budget": False,
            "change_targeting": False,
            "mark_external_post_live_without_confirmation": False,
        },
    }


def dispatch_refresh_payload(
    payload: Mapping[str, Any],
    settings: AutomationDispatchSettings,
) -> AutomationDispatchReceipt:
    if not settings.configured:
        raise CampaignCadenceError(
            "The publishing workflow is not connected. Use the copy-ready package and confirm the external action manually."
        )
    body = serialize_launch_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Credit-Friendly-Homes-Disposition-OS/1.0",
        "X-CFH-Event": CADENCE_EVENT,
    }
    signature = sign_launch_payload(body, settings.signing_secret)
    if signature:
        headers["X-CFH-Signature"] = signature
    request = Request(settings.webhook_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=settings.timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")[:CADENCE_RESPONSE_LIMIT]
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:CADENCE_RESPONSE_LIMIT]
        raise CampaignCadenceError(
            f"The publishing workflow rejected the refresh request (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise CampaignCadenceError(
            "The publishing workflow could not be reached. No external channel was marked refreshed."
        ) from exc
    if not 200 <= status_code < 300:
        raise CampaignCadenceError(
            f"The publishing workflow returned HTTP {status_code}. No external channel was marked refreshed."
        )
    return AutomationDispatchReceipt(
        status_code=status_code,
        sent_at=datetime.now(UTC),
        response_text=response_text,
    )


def mark_refresh_dispatched(
    ledger: CampaignCadenceLedger,
    *,
    task_id: str,
    actor: str,
    receipt: AutomationDispatchReceipt,
) -> CampaignCadenceLedger:
    task = find_refresh_task(ledger, task_id)
    if task is None:
        raise CampaignCadenceError("The selected refresh task could not be found.")
    if task.manager_approval_required and not task.approved_at:
        raise CampaignCadenceError("Management approval is required before dispatch.")
    updated = task.model_copy(
        update={
            "status": RefreshTaskStatus.DISPATCHED,
            "dispatch_detail": (
                f"HTTP {receipt.status_code} at {receipt.sent_at.isoformat()}. "
                f"{receipt.response_text}"
            )[:1500],
            "updated_at": receipt.sent_at,
        }
    )
    return _replace_task(ledger, updated, now=receipt.sent_at)


def queue_rows(items: Sequence[CadenceQueueItem]) -> list[dict[str, str | int]]:
    return [
        {
            "Priority": item.priority.value,
            "Property": item.property_address,
            "Channel": item.channel_name,
            "Mode": item.channel_mode,
            "Launch Status": item.launch_status,
            "Cadence": f"{item.cadence_days} days",
            "Last Activity": (
                item.last_activity_at.astimezone().strftime("%Y-%m-%d %I:%M %p")
                if item.last_activity_at
                else "Never recorded"
            ),
            "Due": (
                item.due_at.astimezone().strftime("%Y-%m-%d %I:%M %p")
                if item.due_at
                else "—"
            ),
            "Days Overdue": item.days_overdue,
            "Clicks 7d": item.clicks_7,
            "Clicks 30d": item.clicks_30,
            "Registrations": item.registrations,
            "Applications": item.applications,
            "Contracts": item.contracts,
            "Required Action": item.action.value,
            "Owner": item.owner,
            "Approval": "Required" if item.manager_approval_required else "Operator",
            "Reason": item.reason,
        }
        for item in items
    ]


def task_rows(tasks: Sequence[CampaignRefreshTask]) -> list[dict[str, str]]:
    return [
        {
            "Priority": task.priority.value,
            "Property": task.property_address,
            "Channel": task.channel_name,
            "Action": task.action.value,
            "Status": task.status.value,
            "Owner": task.owner,
            "Due": task.due_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Approval": "Required" if task.manager_approval_required else "Operator",
            "Approved By": task.approved_by or "—",
            "Completed By": task.completed_by or "—",
            "Reason": task.reason,
            "Notes": task.notes or "—",
        }
        for task in sorted(
            tasks,
            key=lambda item: (
                item.status in CLOSED_TASK_STATUSES,
                item.due_at,
                item.property_address.casefold(),
                item.channel_name.casefold(),
            ),
        )
    ]


def policy_rows(policies: Sequence[ChannelCadencePolicy]) -> list[dict[str, str | int]]:
    return [
        {
            "Channel": CHANNELS_BY_KEY[policy.channel_key].name,
            "Mode": CHANNELS_BY_KEY[policy.channel_key].mode.value,
            "Enabled": "Yes" if policy.enabled else "No",
            "Cadence Days": policy.cadence_days,
            "Warning Days": policy.warning_days,
            "Default Owner": policy.default_owner,
            "Notes": policy.notes or "—",
        }
        for policy in policies
    ]


class CampaignCadenceStore:
    """Private Supabase Storage ledger for 15-channel cadence rules and refresh work."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise CampaignCadenceError("Supabase is not configured for campaign cadence records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise CampaignCadenceError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(CADENCE_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    CADENCE_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": CADENCE_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise CampaignCadenceError(
                    "Could not create the private campaign-cadence bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> CampaignCadenceLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(CADENCE_BUCKET).download(CADENCE_PATH)
        except Exception:
            return ensure_all_policies(CampaignCadenceLedger())
        try:
            payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return ensure_all_policies(CampaignCadenceLedger.model_validate_json(payload))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise CampaignCadenceError(
                "The saved campaign-cadence ledger could not be read."
            ) from exc

    def save(self, ledger: CampaignCadenceLedger) -> None:
        self._ensure_bucket()
        normalized = ensure_all_policies(ledger)
        payload = normalized.model_dump_json().encode("utf-8")
        if len(payload) > CADENCE_MAX_BYTES:
            raise CampaignCadenceError("The campaign-cadence ledger is too large to save.")
        try:
            self._client.storage.from_(CADENCE_BUCKET).upload(
                path=CADENCE_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise CampaignCadenceError(
                "Could not save the campaign-cadence ledger."
            ) from exc
