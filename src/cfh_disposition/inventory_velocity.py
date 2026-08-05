from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .analytics import ClickEvent
from .campaign_launch import CampaignLaunchState, LaunchStatus, ensure_all_channels
from .dwelyx_attribution import (
    STAGE_RANK,
    DwelyxAttributionEvent,
    JourneySnapshot,
    JourneyStage,
    build_journeys,
)
from .models import OwnerFinanceProperty, PropertyStatus
from .storage import SupabaseSettings

INVENTORY_VELOCITY_BUCKET = "cfh-inventory-velocity"
INVENTORY_VELOCITY_PATH = "inventory-velocity/ledger.json"
INVENTORY_VELOCITY_MAX_BYTES = 3 * 1024 * 1024
ACTIVE_PROPERTY_STATUSES = {PropertyStatus.READY, PropertyStatus.LIVE}


class InventoryVelocityError(RuntimeError):
    """Raised when the inventory escalation workflow cannot complete."""


class EscalationLevel(StrEnum):
    CRITICAL = "Critical"
    HIGH = "High"
    WATCH = "Watch"
    NORMAL = "Normal"
    CLOSED = "Not Active"


class FunnelBottleneck(StrEnum):
    NOT_LIVE = "Marketing Not Fully Live"
    NO_TRAFFIC = "No Meaningful Traffic"
    DATA_GAP = "Dwelyx Results Connection Gap"
    CLICK_NO_REGISTRATION = "Clicks Without Registrations"
    REGISTRATION_NO_APPLICATION = "Registrations Without Applications"
    APPLICATION_NO_SHOWING = "Applications Without Showings"
    SHOWING_NO_CONTRACT = "Showings Without a Contract"
    CONTRACT_IN_PROGRESS = "Contract in Progress"
    HEALTHY = "Funnel Moving"
    INACTIVE = "Property Not in Active Vacant Inventory"


class InterventionType(StrEnum):
    ACTIVATE_CHANNELS = "Activate Missing Channels"
    VERIFY_LISTINGS = "Verify Listings and Links"
    CONNECT_DWELYX = "Connect Dwelyx Results"
    REFRESH_CREATIVE = "Refresh Creative and Photos"
    FIX_LANDING_PAGE = "Review Property Page and Offer Message"
    REVIEW_TERMS = "Manager Review of Terms"
    IMPROVE_APPLICATION_FOLLOW_UP = "Improve Application Follow-Up"
    FIX_SHOWING_PROCESS = "Fix Showing Process"
    MANAGER_PRICE_CONDITION_REVIEW = "Manager Price, Condition, and Terms Review"
    HOLD_COURSE = "Keep Running Current Plan"


class EscalationTaskStatus(StrEnum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    DISMISSED = "Dismissed"


class PropertyVelocityProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    property_id: str
    marketing_started_at: datetime | None = None
    target_fill_days: int = Field(default=21, ge=1, le=365)
    daily_holding_cost: Decimal = Field(default=Decimal("0"), ge=0)
    assigned_owner: str = Field(default="Sabrina", max_length=120)
    notes: str = Field(default="", max_length=2000)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EscalationTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    property_id: str
    intervention_type: InterventionType
    title: str = Field(min_length=5, max_length=300)
    reason: str = Field(min_length=5, max_length=1500)
    owner: str = Field(default="Sabrina", max_length=120)
    due_at: datetime
    status: EscalationTaskStatus = EscalationTaskStatus.OPEN
    manager_approval_required: bool = False
    recommended_change: str = Field(default="", max_length=1500)
    notes: str = Field(default="", max_length=2000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class InventoryVelocityLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    profiles: list[PropertyVelocityProfile] = Field(default_factory=list)
    tasks: list[EscalationTask] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PropertySignals:
    property_id: str
    address: str
    status: str
    occupancy: str
    marketing_started_at: datetime
    marketing_age_source: str
    days_marketed: int
    target_fill_days: int
    active_channels: int
    manual_channels_ready: int
    failed_channels: int
    clicks_7: int
    clicks_30: int
    registrations: int
    applications: int
    showings: int
    contracts: int
    filled: int
    latest_result_at: datetime | None
    daily_holding_cost: Decimal
    estimated_holding_cost: Decimal
    attribution_connected: bool


@dataclass(frozen=True, slots=True)
class PropertyVelocityAssessment:
    signals: PropertySignals
    level: EscalationLevel
    score: int
    bottleneck: FunnelBottleneck
    diagnosis: str
    primary_intervention: InterventionType
    primary_action: str
    due_hours: int
    manager_approval_required: bool
    supporting_actions: tuple[str, ...]


LEVEL_SORT = {
    EscalationLevel.CRITICAL: 0,
    EscalationLevel.HIGH: 1,
    EscalationLevel.WATCH: 2,
    EscalationLevel.NORMAL: 3,
    EscalationLevel.CLOSED: 4,
}


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def _is_vacant(value: str) -> bool:
    normalized = value.strip().casefold()
    return any(word in normalized for word in ("vacant", "empty", "unoccupied"))


def profile_for_property(
    ledger: InventoryVelocityLedger,
    property_id: str,
) -> PropertyVelocityProfile | None:
    return next((item for item in ledger.profiles if item.property_id == property_id), None)


def upsert_profile(
    ledger: InventoryVelocityLedger,
    profile: PropertyVelocityProfile,
    *,
    now: datetime | None = None,
) -> InventoryVelocityLedger:
    current = _current(now)
    saved = profile.model_copy(update={"updated_at": current})
    profiles = [
        saved if item.property_id == saved.property_id else item
        for item in ledger.profiles
    ]
    if not any(item.property_id == saved.property_id for item in ledger.profiles):
        profiles.append(saved)
    return ledger.model_copy(update={"profiles": profiles, "updated_at": current})


def _marketing_start(
    property_record: OwnerFinanceProperty,
    profile: PropertyVelocityProfile | None,
    launch_state: CampaignLaunchState | None,
) -> tuple[datetime, str]:
    if profile and profile.marketing_started_at:
        return _current(profile.marketing_started_at), "Saved marketing start date"
    if launch_state and launch_state.approved_at:
        return _current(launch_state.approved_at), "Campaign approval date"
    if launch_state:
        channel_dates = [
            record.updated_at
            for record in ensure_all_channels(launch_state).channels.values()
            if record.updated_at
            and record.status in {LaunchStatus.POSTED, LaunchStatus.SCHEDULED}
        ]
        if channel_dates:
            return min(_current(value) for value in channel_dates), "First active channel date"
    return _current(property_record.created_at), "Property record created date"


def _channel_counts(launch_state: CampaignLaunchState | None) -> tuple[int, int, int]:
    if launch_state is None:
        return 0, 0, 0
    state = ensure_all_channels(launch_state)
    active = sum(
        record.status in {LaunchStatus.POSTED, LaunchStatus.SCHEDULED}
        for record in state.channels.values()
    )
    ready = sum(record.status == LaunchStatus.READY for record in state.channels.values())
    failed = sum(record.status == LaunchStatus.FAILED for record in state.channels.values())
    return active, ready, failed


def _journey_reached(journey: JourneySnapshot, stage: JourneyStage) -> bool:
    return STAGE_RANK[journey.stage] >= STAGE_RANK[stage]


def build_property_signals(
    property_record: OwnerFinanceProperty,
    *,
    ledger: InventoryVelocityLedger,
    click_events: Sequence[ClickEvent] = (),
    attribution_events: Sequence[DwelyxAttributionEvent] = (),
    launch_state: CampaignLaunchState | None = None,
    attribution_connected: bool = False,
    now: datetime | None = None,
) -> PropertySignals:
    current = _current(now)
    property_id = str(property_record.property_id)
    profile = profile_for_property(ledger, property_id)
    started_at, source = _marketing_start(property_record, profile, launch_state)
    days_marketed = max(0, int((current - started_at).total_seconds() // 86400))
    target_days = profile.target_fill_days if profile else 21
    daily_cost = profile.daily_holding_cost if profile else Decimal("0")
    active_channels, manual_ready, failed_channels = _channel_counts(launch_state)

    clicks = [
        event
        for event in click_events
        if event.property_id == property_id and event.occurred_at <= current
    ]
    clicks_7 = sum(event.occurred_at >= current - timedelta(days=7) for event in clicks)
    clicks_30 = sum(event.occurred_at >= current - timedelta(days=30) for event in clicks)

    real_events = [
        event
        for event in attribution_events
        if not event.test_mode and event.cfh_property_id == property_id
    ]
    journeys = build_journeys(real_events)
    registrations = sum(
        _journey_reached(item, JourneyStage.REGISTERED) for item in journeys
    )
    applications = sum(
        _journey_reached(item, JourneyStage.APPLICATION_SUBMITTED)
        for item in journeys
    )
    showings = sum(
        _journey_reached(item, JourneyStage.SHOWING_SCHEDULED)
        for item in journeys
    )
    contracts = sum(
        _journey_reached(item, JourneyStage.CONTRACT_SIGNED)
        for item in journeys
    )
    filled = sum(_journey_reached(item, JourneyStage.FILLED) for item in journeys)
    latest_result = max((item.latest_event_at for item in journeys), default=None)

    return PropertySignals(
        property_id=property_id,
        address=property_record.display_address,
        status=property_record.status.value,
        occupancy=property_record.occupancy,
        marketing_started_at=started_at,
        marketing_age_source=source,
        days_marketed=days_marketed,
        target_fill_days=target_days,
        active_channels=active_channels,
        manual_channels_ready=manual_ready,
        failed_channels=failed_channels,
        clicks_7=clicks_7,
        clicks_30=clicks_30,
        registrations=registrations,
        applications=applications,
        showings=showings,
        contracts=contracts,
        filled=filled,
        latest_result_at=latest_result,
        daily_holding_cost=daily_cost,
        estimated_holding_cost=daily_cost * Decimal(days_marketed),
        attribution_connected=attribution_connected,
    )


def _pressure_score(signals: PropertySignals) -> int:
    score = 0
    over_target = signals.days_marketed - signals.target_fill_days
    if over_target >= 21:
        score += 40
    elif over_target >= 14:
        score += 30
    elif over_target >= 7:
        score += 20
    elif over_target > 0:
        score += 10

    if signals.active_channels == 0:
        score += 35
    elif signals.active_channels < 5:
        score += 20
    elif signals.active_channels < 10:
        score += 10
    if signals.failed_channels:
        score += min(15, signals.failed_channels * 5)
    if signals.days_marketed >= 3 and signals.clicks_30 == 0:
        score += 25
    if signals.clicks_30 >= 10 and signals.registrations == 0:
        score += 25
    if signals.registrations >= 3 and signals.applications == 0:
        score += 25
    if signals.applications >= 2 and signals.showings == 0:
        score += 25
    if signals.showings >= 2 and signals.contracts == 0:
        score += 30
    return min(score, 100)


def _level_for_score(score: int) -> EscalationLevel:
    if score >= 70:
        return EscalationLevel.CRITICAL
    if score >= 45:
        return EscalationLevel.HIGH
    if score >= 20:
        return EscalationLevel.WATCH
    return EscalationLevel.NORMAL


def assess_property(signals: PropertySignals) -> PropertyVelocityAssessment:
    active_inventory = (
        signals.status in {status.value for status in ACTIVE_PROPERTY_STATUSES}
        and _is_vacant(signals.occupancy)
        and signals.filled == 0
    )
    if not active_inventory:
        return PropertyVelocityAssessment(
            signals=signals,
            level=EscalationLevel.CLOSED,
            score=0,
            bottleneck=FunnelBottleneck.INACTIVE,
            diagnosis="This property is not currently active vacant inventory.",
            primary_intervention=InterventionType.HOLD_COURSE,
            primary_action="No disposition escalation is required while this property is inactive or occupied.",
            due_hours=168,
            manager_approval_required=False,
            supporting_actions=(),
        )

    score = _pressure_score(signals)
    level = _level_for_score(score)
    supporting: list[str] = []

    if signals.contracts > 0:
        bottleneck = FunnelBottleneck.CONTRACT_IN_PROGRESS
        intervention = InterventionType.IMPROVE_APPLICATION_FOLLOW_UP
        diagnosis = "A signed contract result exists. Protecting and completing that buyer file is now the highest priority."
        action = "Confirm signatures, funds, documents, move-in steps, and property shutdown timing before refreshing marketing."
        due_hours = 12
        manager_required = False
    elif signals.active_channels == 0:
        bottleneck = FunnelBottleneck.NOT_LIVE
        intervention = InterventionType.ACTIVATE_CHANNELS
        diagnosis = "No marketing channel is recorded as Posted or Scheduled for this vacant home."
        action = "Open the Campaign Launch Center, complete the launch gate, and activate every supported channel."
        due_hours = 4
        manager_required = False
    elif signals.active_channels < 5 or signals.failed_channels:
        bottleneck = FunnelBottleneck.NOT_LIVE
        intervention = InterventionType.VERIFY_LISTINGS
        diagnosis = (
            f"Only {signals.active_channels} channels are active and "
            f"{signals.failed_channels} channel failures are recorded."
        )
        action = "Verify every live listing and tracked link, then repair failed or unfinished channel tasks."
        due_hours = 8
        manager_required = False
    elif signals.days_marketed >= 3 and signals.clicks_30 == 0:
        bottleneck = FunnelBottleneck.NO_TRAFFIC
        intervention = InterventionType.REFRESH_CREATIVE
        diagnosis = "The property is marketed but has produced no tracked traffic in the last 30 days."
        action = "Refresh the lead photo and opening message, then relaunch the strongest eligible channels."
        due_hours = 12
        manager_required = False
    elif signals.clicks_30 > 0 and not signals.attribution_connected:
        bottleneck = FunnelBottleneck.DATA_GAP
        intervention = InterventionType.CONNECT_DWELYX
        diagnosis = "Traffic is reaching Dwelyx, but live Dwelyx registration and application results are not connected yet."
        action = "Finish the secure Dwelyx results connection before judging whether the offer or follow-up is failing."
        due_hours = 24
        manager_required = False
    elif signals.clicks_30 >= 10 and signals.registrations == 0:
        bottleneck = FunnelBottleneck.CLICK_NO_REGISTRATION
        intervention = InterventionType.FIX_LANDING_PAGE
        diagnosis = "Buyers are clicking, but none are registering in Dwelyx for this property."
        action = "Review the property page, exact terms, photos, condition disclosures, and registration call to action."
        due_hours = 24
        manager_required = False
    elif signals.registrations >= 3 and signals.applications == 0:
        bottleneck = FunnelBottleneck.REGISTRATION_NO_APPLICATION
        intervention = InterventionType.REVIEW_TERMS
        diagnosis = "Buyers are registering, but the property is not producing submitted applications."
        action = "Review application friction and have management compare the down payment and monthly payment with buyer demand."
        due_hours = 24
        manager_required = True
    elif signals.applications >= 2 and signals.showings == 0:
        bottleneck = FunnelBottleneck.APPLICATION_NO_SHOWING
        intervention = InterventionType.FIX_SHOWING_PROCESS
        diagnosis = "Applications exist, but no showing has been scheduled."
        action = "Audit response speed, showing instructions, access, confirmation messages, and assigned follow-up ownership."
        due_hours = 12
        manager_required = False
    elif signals.showings >= 2 and signals.contracts == 0:
        bottleneck = FunnelBottleneck.SHOWING_NO_CONTRACT
        intervention = InterventionType.MANAGER_PRICE_CONDITION_REVIEW
        diagnosis = "Multiple buyers reached a showing, but no contract was signed."
        action = "Management must review buyer objections, condition, total price, down payment, and monthly payment before the next campaign cycle."
        due_hours = 24
        manager_required = True
    else:
        bottleneck = FunnelBottleneck.HEALTHY
        intervention = InterventionType.HOLD_COURSE
        diagnosis = "The funnel is moving and has not crossed a clear intervention threshold."
        action = "Keep the current plan running and review new traffic and Dwelyx results within seven days."
        due_hours = 168
        manager_required = False

    if signals.manual_channels_ready:
        supporting.append(
            f"Complete {signals.manual_channels_ready} channels still marked Ready for manual final publication."
        )
    if signals.days_marketed > signals.target_fill_days:
        supporting.append(
            f"The home is {signals.days_marketed - signals.target_fill_days} days beyond its target fill window."
        )
    if signals.daily_holding_cost > 0:
        supporting.append(
            f"Estimated holding-cost exposure is ${signals.estimated_holding_cost:,.0f} using the saved daily cost."
        )
    if level == EscalationLevel.CRITICAL and intervention not in {
        InterventionType.MANAGER_PRICE_CONDITION_REVIEW,
        InterventionType.REVIEW_TERMS,
    }:
        supporting.append("Require a manager decision within 24 hours because the total pressure score is critical.")

    return PropertyVelocityAssessment(
        signals=signals,
        level=level,
        score=score,
        bottleneck=bottleneck,
        diagnosis=diagnosis,
        primary_intervention=intervention,
        primary_action=action,
        due_hours=due_hours,
        manager_approval_required=manager_required,
        supporting_actions=tuple(supporting),
    )


def build_velocity_queue(
    properties: Sequence[OwnerFinanceProperty],
    *,
    ledger: InventoryVelocityLedger,
    click_events: Sequence[ClickEvent] = (),
    attribution_events: Sequence[DwelyxAttributionEvent] = (),
    launch_states: Mapping[str, CampaignLaunchState | None] | None = None,
    attribution_connected: bool = False,
    now: datetime | None = None,
) -> list[PropertyVelocityAssessment]:
    states = launch_states or {}
    rows = [
        assess_property(
            build_property_signals(
                item,
                ledger=ledger,
                click_events=click_events,
                attribution_events=attribution_events,
                launch_state=states.get(str(item.property_id)),
                attribution_connected=attribution_connected,
                now=now,
            )
        )
        for item in properties
    ]
    return sorted(
        rows,
        key=lambda item: (
            LEVEL_SORT[item.level],
            -item.score,
            -item.signals.days_marketed,
            item.signals.address.casefold(),
        ),
    )


def suggested_task(
    assessment: PropertyVelocityAssessment,
    *,
    owner: str = "",
    now: datetime | None = None,
) -> EscalationTask:
    current = _current(now)
    assigned = owner.strip() or "Sabrina"
    recommendation = (
        "Management review only. This task does not authorize any change to price, down payment, monthly payment, or advertising spend."
        if assessment.manager_approval_required
        else ""
    )
    return EscalationTask(
        property_id=assessment.signals.property_id,
        intervention_type=assessment.primary_intervention,
        title=f"{assessment.primary_intervention.value} — {assessment.signals.address}",
        reason=assessment.diagnosis,
        owner=assigned,
        due_at=current + timedelta(hours=assessment.due_hours),
        manager_approval_required=assessment.manager_approval_required,
        recommended_change=recommendation,
        notes="\n".join(assessment.supporting_actions),
        created_at=current,
        updated_at=current,
    )


def add_escalation_task(
    ledger: InventoryVelocityLedger,
    task: EscalationTask,
    *,
    now: datetime | None = None,
) -> InventoryVelocityLedger:
    duplicate = next(
        (
            item
            for item in ledger.tasks
            if item.property_id == task.property_id
            and item.intervention_type == task.intervention_type
            and item.status in {EscalationTaskStatus.OPEN, EscalationTaskStatus.IN_PROGRESS}
        ),
        None,
    )
    if duplicate:
        raise InventoryVelocityError("An open task for this property and intervention already exists.")
    current = _current(now)
    saved = task.model_copy(update={"created_at": current, "updated_at": current})
    return ledger.model_copy(
        update={"tasks": [*ledger.tasks, saved], "updated_at": current}
    )


def update_escalation_task(
    ledger: InventoryVelocityLedger,
    *,
    task_id: str,
    status: EscalationTaskStatus,
    owner: str,
    notes: str = "",
    now: datetime | None = None,
) -> InventoryVelocityLedger:
    current = _current(now)
    matched = False
    tasks: list[EscalationTask] = []
    for task in ledger.tasks:
        if task.task_id != task_id:
            tasks.append(task)
            continue
        matched = True
        tasks.append(
            task.model_copy(
                update={
                    "status": status,
                    "owner": owner.strip() or task.owner,
                    "notes": notes.strip(),
                    "updated_at": current,
                    "completed_at": (
                        current
                        if status in {
                            EscalationTaskStatus.COMPLETED,
                            EscalationTaskStatus.DISMISSED,
                        }
                        else None
                    ),
                }
            )
        )
    if not matched:
        raise InventoryVelocityError("The selected escalation task could not be found.")
    return ledger.model_copy(update={"tasks": tasks, "updated_at": current})


def queue_rows(
    assessments: Sequence[PropertyVelocityAssessment],
) -> list[dict[str, str | int]]:
    return [
        {
            "Priority": item.level.value,
            "Score": item.score,
            "Property": item.signals.address,
            "Days Marketed": item.signals.days_marketed,
            "Target Days": item.signals.target_fill_days,
            "Active Channels": item.signals.active_channels,
            "Clicks 30d": item.signals.clicks_30,
            "Registrations": item.signals.registrations,
            "Applications": item.signals.applications,
            "Showings": item.signals.showings,
            "Contracts": item.signals.contracts,
            "Bottleneck": item.bottleneck.value,
            "Next Action": item.primary_action,
            "Manager Approval": "Required" if item.manager_approval_required else "No",
            "Holding Exposure": (
                f"${item.signals.estimated_holding_cost:,.0f}"
                if item.signals.daily_holding_cost > 0
                else "Not entered"
            ),
        }
        for item in assessments
        if item.level != EscalationLevel.CLOSED
    ]


def task_rows(
    ledger: InventoryVelocityLedger,
    property_labels: Mapping[str, str] | None = None,
) -> list[dict[str, str]]:
    labels = property_labels or {}
    return [
        {
            "Property": labels.get(task.property_id, task.property_id),
            "Task": task.intervention_type.value,
            "Owner": task.owner,
            "Status": task.status.value,
            "Due": task.due_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Manager Approval": "Required" if task.manager_approval_required else "No",
            "Reason": task.reason,
            "Notes": task.notes or "—",
        }
        for task in sorted(
            ledger.tasks,
            key=lambda item: (
                item.status in {
                    EscalationTaskStatus.COMPLETED,
                    EscalationTaskStatus.DISMISSED,
                },
                item.due_at,
            ),
        )
    ]


class InventoryVelocityStore:
    """Private Supabase Storage ledger for inventory settings and escalation tasks."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise InventoryVelocityError("Supabase is not configured for inventory escalation records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise InventoryVelocityError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(INVENTORY_VELOCITY_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    INVENTORY_VELOCITY_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": INVENTORY_VELOCITY_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise InventoryVelocityError(
                    "Could not create the private inventory-velocity bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> InventoryVelocityLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(INVENTORY_VELOCITY_BUCKET).download(
                INVENTORY_VELOCITY_PATH
            )
        except Exception:
            return InventoryVelocityLedger()
        try:
            payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return InventoryVelocityLedger.model_validate_json(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InventoryVelocityError(
                "The saved inventory-velocity ledger could not be read."
            ) from exc

    def save(self, ledger: InventoryVelocityLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > INVENTORY_VELOCITY_MAX_BYTES:
            raise InventoryVelocityError("The inventory-velocity ledger is too large to save.")
        try:
            self._client.storage.from_(INVENTORY_VELOCITY_BUCKET).upload(
                path=INVENTORY_VELOCITY_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise InventoryVelocityError(
                "Could not save inventory escalation records."
            ) from exc
