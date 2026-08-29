from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .fact_lock import MARKETABLE_PROPERTY_STATUSES
from .models import BuyerProfile, OwnerFinanceProperty, PropertyStatus
from .storage import SupabaseSettings

BUYER_CONVERSION_BUCKET = "cfh-buyer-conversion"
BUYER_CONVERSION_PATH = "buyer-conversion/ledger.json"
BUYER_CONVERSION_MAX_BYTES = 4 * 1024 * 1024


class BuyerConversionError(RuntimeError):
    """Raised when the buyer conversion pipeline cannot complete an operation."""


class ConversionStage(StrEnum):
    NEW_LEAD = "New Lead"
    CONTACTED = "Contacted"
    QUALIFIED = "Qualified"
    APPLICATION_STARTED = "Application Started"
    APPLICATION_SUBMITTED = "Application Submitted"
    SHOWING_SCHEDULED = "Showing Scheduled"
    SHOWING_COMPLETED = "Showing Completed"
    APPROVED = "Approved"
    CONTRACT_PENDING = "Contract Pending"
    FILLED = "Filled / Contracted"
    PAUSED = "Paused"
    LOST = "Lost"


class ConversionPriority(StrEnum):
    COMPLIANCE_HOLD = "Compliance Hold"
    URGENT = "Urgent"
    HIGH = "High"
    NORMAL = "Normal"
    NURTURE = "Nurture"
    CLOSED = "Closed"


class ActivityType(StrEnum):
    CONTACT_ATTEMPT = "Contact Attempt"
    EMAIL_SENT = "Email Sent"
    SMS_SENT = "SMS Sent"
    CALL_CONNECTED = "Call Connected"
    BUYER_REPLY = "Buyer Reply"
    APPLICATION_LINK_SENT = "Application Link Sent"
    SHOWING_CONFIRMED = "Showing Confirmed"
    NOTE = "Note"


TERMINAL_STAGES = {ConversionStage.FILLED, ConversionStage.LOST}
APPLICATION_STAGES = {
    ConversionStage.APPLICATION_STARTED,
    ConversionStage.APPLICATION_SUBMITTED,
    ConversionStage.SHOWING_SCHEDULED,
    ConversionStage.SHOWING_COMPLETED,
    ConversionStage.APPROVED,
    ConversionStage.CONTRACT_PENDING,
    ConversionStage.FILLED,
}
SHOWING_STAGES = {
    ConversionStage.SHOWING_SCHEDULED,
    ConversionStage.SHOWING_COMPLETED,
    ConversionStage.APPROVED,
    ConversionStage.CONTRACT_PENDING,
    ConversionStage.FILLED,
}
CONTRACT_STAGES = {
    ConversionStage.CONTRACT_PENDING,
    ConversionStage.FILLED,
}
CONTACT_ACTIVITIES = {
    ActivityType.CONTACT_ATTEMPT,
    ActivityType.EMAIL_SENT,
    ActivityType.SMS_SENT,
    ActivityType.CALL_CONNECTED,
    ActivityType.BUYER_REPLY,
    ActivityType.APPLICATION_LINK_SENT,
    ActivityType.SHOWING_CONFIRMED,
}

STAGE_STALL_HOURS: dict[ConversionStage, int] = {
    ConversionStage.NEW_LEAD: 24,
    ConversionStage.CONTACTED: 48,
    ConversionStage.QUALIFIED: 48,
    ConversionStage.APPLICATION_STARTED: 48,
    ConversionStage.APPLICATION_SUBMITTED: 48,
    ConversionStage.SHOWING_SCHEDULED: 36,
    ConversionStage.SHOWING_COMPLETED: 24,
    ConversionStage.APPROVED: 24,
    ConversionStage.CONTRACT_PENDING: 24,
    ConversionStage.PAUSED: 168,
}

PRIORITY_SORT = {
    ConversionPriority.COMPLIANCE_HOLD: 0,
    ConversionPriority.URGENT: 1,
    ConversionPriority.HIGH: 2,
    ConversionPriority.NORMAL: 3,
    ConversionPriority.NURTURE: 4,
    ConversionPriority.CLOSED: 5,
}


class ConversionRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    record_id: str = Field(default_factory=lambda: str(uuid4()))
    buyer_id: str
    property_id: str
    stage: ConversionStage = ConversionStage.NEW_LEAD
    owner: str = Field(default="Sabrina", max_length=120)
    source: str = Field(default="Dwelyx", max_length=160)
    campaign: str = Field(default="", max_length=200)
    next_action: str = Field(default="Review buyer fit and make the first permitted contact.", max_length=1000)
    next_action_at: datetime | None = None
    last_activity_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_contact_at: datetime | None = None
    contact_attempts: int = Field(default=0, ge=0, le=10000)
    lost_reason: str = Field(default="", max_length=1000)
    paused_reason: str = Field(default="", max_length=1000)
    notes: str = Field(default="", max_length=4000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_terminal_reason(self) -> ConversionRecord:
        if self.stage == ConversionStage.LOST and not self.lost_reason:
            raise ValueError("A lost reason is required when a buyer is marked Lost")
        if self.stage == ConversionStage.PAUSED and not self.paused_reason:
            raise ValueError("A pause reason is required when a buyer is marked Paused")
        return self


class ConversionEvent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    record_id: str
    event_type: str = Field(min_length=2, max_length=160)
    from_stage: str = ""
    to_stage: str = ""
    actor: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BuyerConversionLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    records: list[ConversionRecord] = Field(default_factory=list)
    events: list[ConversionEvent] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ConversionQueueItem:
    record_id: str
    priority: ConversionPriority
    stage: ConversionStage
    buyer_name: str
    property_address: str
    property_status: str
    owner: str
    days_idle: int
    overdue_days: int
    next_action: str
    next_action_at: datetime | None
    recommended_action: str
    reason: str
    contact_channels: tuple[str, ...]
    contact_block: str
    contact_attempts: int


@dataclass(frozen=True, slots=True)
class FunnelSnapshot:
    total_records: int
    active_records: int
    overdue_records: int
    compliance_holds: int
    new_leads: int
    contacted: int
    qualified: int
    applications: int
    showings: int
    approved: int
    contracts: int
    filled: int
    lost: int
    application_rate: float
    fill_rate: float


@dataclass(frozen=True, slots=True)
class PropertyPipelineSummary:
    property_id: str
    property_address: str
    property_status: str
    active_buyers: int
    overdue_buyers: int
    applications: int
    showings: int
    approvals: int
    contracts: int
    filled: int
    lost: int


def _current(now: datetime | None = None) -> datetime:
    value = now or datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _buyer_name(buyer: BuyerProfile | None, buyer_id: str) -> str:
    if buyer is None:
        return f"Unknown buyer {buyer_id[:8]}"
    name = " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip()
    return name or f"Buyer {buyer_id[:8]}"


def _property_address(property_record: OwnerFinanceProperty | None, property_id: str) -> str:
    if property_record is None:
        return f"Unknown property {property_id[:8]}"
    return property_record.display_address or f"Property {property_id[:8]}"


def _find_record(ledger: BuyerConversionLedger, record_id: str) -> ConversionRecord:
    for record in ledger.records:
        if record.record_id == record_id:
            return record
    raise BuyerConversionError("The selected conversion record could not be found.")


def _replace_record(ledger: BuyerConversionLedger, updated: ConversionRecord, event: ConversionEvent) -> BuyerConversionLedger:
    records = [updated if record.record_id == updated.record_id else record for record in ledger.records]
    return ledger.model_copy(
        update={
            "records": records,
            "events": [*ledger.events, event],
            "updated_at": event.occurred_at,
        }
    )


def default_next_action(stage: ConversionStage) -> str:
    actions = {
        ConversionStage.NEW_LEAD: "Review buyer fit and make the first permitted contact.",
        ConversionStage.CONTACTED: "Confirm the buyer's monthly-payment, down-payment, location, and move-timing fit.",
        ConversionStage.QUALIFIED: "Send or confirm the Dwelyx application and explain the next step.",
        ConversionStage.APPLICATION_STARTED: "Follow up on the incomplete application and identify the blocker.",
        ConversionStage.APPLICATION_SUBMITTED: "Review the application and schedule the next property step.",
        ConversionStage.SHOWING_SCHEDULED: "Confirm the showing and provide approved access instructions.",
        ConversionStage.SHOWING_COMPLETED: "Record the buyer decision and move the file toward approval or loss.",
        ConversionStage.APPROVED: "Prepare the contract package and confirm required funds and documents.",
        ConversionStage.CONTRACT_PENDING: "Finish signatures, funds, and the move-in or closing checklist.",
        ConversionStage.PAUSED: "Review the pause reason and decide whether to resume, reassign, or close the file.",
        ConversionStage.FILLED: "No follow-up required. The property is filled or contracted.",
        ConversionStage.LOST: "No follow-up required unless a new opportunity is created.",
    }
    return actions[stage]


def default_follow_up_at(stage: ConversionStage, *, now: datetime | None = None) -> datetime | None:
    current = _current(now)
    delays = {
        ConversionStage.NEW_LEAD: timedelta(hours=2),
        ConversionStage.CONTACTED: timedelta(days=1),
        ConversionStage.QUALIFIED: timedelta(days=1),
        ConversionStage.APPLICATION_STARTED: timedelta(days=1),
        ConversionStage.APPLICATION_SUBMITTED: timedelta(days=1),
        ConversionStage.SHOWING_SCHEDULED: timedelta(days=1),
        ConversionStage.SHOWING_COMPLETED: timedelta(hours=12),
        ConversionStage.APPROVED: timedelta(hours=12),
        ConversionStage.CONTRACT_PENDING: timedelta(hours=12),
        ConversionStage.PAUSED: timedelta(days=7),
    }
    return current + delays[stage] if stage in delays else None


def contact_permissions(buyer: BuyerProfile | None) -> tuple[tuple[str, ...], str]:
    if buyer is None:
        return (), "Buyer record is missing."
    if buyer.do_not_contact:
        return (), "Buyer is marked Do Not Contact."
    channels: list[str] = []
    if buyer.email_consent and buyer.email:
        channels.append("Email")
    if buyer.sms_consent and buyer.phone:
        channels.append("SMS")
    if buyer.call_consent and buyer.phone:
        channels.append("Phone")
    if not channels:
        return (), "No saved contact consent is available."
    return tuple(channels), ""


def create_conversion_record(
    ledger: BuyerConversionLedger,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    *,
    owner: str = "Sabrina",
    source: str = "Dwelyx",
    campaign: str = "",
    notes: str = "",
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    if buyer.do_not_contact:
        raise BuyerConversionError("This buyer is marked Do Not Contact and cannot be added to a new follow-up sequence.")
    if property_record.status not in MARKETABLE_PROPERTY_STATUSES:
        raise BuyerConversionError(
            "New buyer conversion work requires a property that is Ready to Launch or Marketing Live."
        )
    duplicate = next(
        (
            record
            for record in ledger.records
            if record.buyer_id == str(buyer.buyer_id)
            and record.property_id == str(property_record.property_id)
            and record.stage not in TERMINAL_STAGES
        ),
        None,
    )
    if duplicate is not None:
        raise BuyerConversionError("An active buyer/property conversion record already exists.")
    record = ConversionRecord(
        buyer_id=str(buyer.buyer_id),
        property_id=str(property_record.property_id),
        owner=owner or "Unassigned",
        source=source or "Unknown",
        campaign=campaign,
        notes=notes,
        next_action=default_next_action(ConversionStage.NEW_LEAD),
        next_action_at=default_follow_up_at(ConversionStage.NEW_LEAD, now=current),
        last_activity_at=current,
        created_at=current,
        updated_at=current,
    )
    event = ConversionEvent(
        record_id=record.record_id,
        event_type="Record Created",
        to_stage=record.stage.value,
        actor=owner,
        notes=notes,
        occurred_at=current,
    )
    return ledger.model_copy(
        update={
            "records": [*ledger.records, record],
            "events": [*ledger.events, event],
            "updated_at": current,
        }
    )


def transition_record(
    ledger: BuyerConversionLedger,
    *,
    record_id: str,
    new_stage: ConversionStage,
    actor: str,
    notes: str = "",
    lost_reason: str = "",
    paused_reason: str = "",
    next_action: str = "",
    next_action_at: datetime | None = None,
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    record = _find_record(ledger, record_id)
    if record.stage in TERMINAL_STAGES:
        raise BuyerConversionError("A closed conversion record cannot be moved to another stage.")
    if new_stage == record.stage:
        raise BuyerConversionError("Select a different stage before saving.")
    if new_stage == ConversionStage.LOST and not lost_reason.strip():
        raise BuyerConversionError("Enter a lost reason before marking the buyer Lost.")
    if new_stage == ConversionStage.PAUSED and not paused_reason.strip():
        raise BuyerConversionError("Enter a pause reason before pausing the buyer.")

    terminal = new_stage in TERMINAL_STAGES
    resolved_action = "" if terminal else (next_action.strip() or default_next_action(new_stage))
    resolved_due = None if terminal else (next_action_at or default_follow_up_at(new_stage, now=current))
    updated = record.model_copy(
        update={
            "stage": new_stage,
            "next_action": resolved_action,
            "next_action_at": resolved_due,
            "last_activity_at": current,
            "lost_reason": lost_reason.strip() if new_stage == ConversionStage.LOST else "",
            "paused_reason": paused_reason.strip() if new_stage == ConversionStage.PAUSED else "",
            "updated_at": current,
        }
    )
    event = ConversionEvent(
        record_id=record.record_id,
        event_type="Stage Changed",
        from_stage=record.stage.value,
        to_stage=new_stage.value,
        actor=actor,
        notes=notes or lost_reason or paused_reason,
        occurred_at=current,
    )
    return _replace_record(ledger, updated, event)


def record_activity(
    ledger: BuyerConversionLedger,
    *,
    record_id: str,
    activity_type: ActivityType,
    actor: str,
    notes: str = "",
    next_action: str = "",
    next_action_at: datetime | None = None,
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    record = _find_record(ledger, record_id)
    if record.stage in TERMINAL_STAGES:
        raise BuyerConversionError("Activity cannot be added to a closed conversion record.")
    contact_activity = activity_type in CONTACT_ACTIVITIES
    updated = record.model_copy(
        update={
            "last_activity_at": current,
            "last_contact_at": current if contact_activity else record.last_contact_at,
            "contact_attempts": record.contact_attempts + (1 if activity_type == ActivityType.CONTACT_ATTEMPT else 0),
            "next_action": next_action.strip() or record.next_action,
            "next_action_at": next_action_at if next_action_at is not None else record.next_action_at,
            "updated_at": current,
        }
    )
    event = ConversionEvent(
        record_id=record.record_id,
        event_type=activity_type.value,
        from_stage=record.stage.value,
        to_stage=record.stage.value,
        actor=actor,
        notes=notes,
        occurred_at=current,
    )
    return _replace_record(ledger, updated, event)


def schedule_follow_up(
    ledger: BuyerConversionLedger,
    *,
    record_id: str,
    next_action: str,
    next_action_at: datetime,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> BuyerConversionLedger:
    if not next_action.strip():
        raise BuyerConversionError("Enter the next action before scheduling follow-up.")
    current = _current(now)
    due = _current(next_action_at)
    record = _find_record(ledger, record_id)
    if record.stage in TERMINAL_STAGES:
        raise BuyerConversionError("Follow-up cannot be scheduled for a closed conversion record.")
    updated = record.model_copy(
        update={
            "next_action": next_action.strip(),
            "next_action_at": due,
            "updated_at": current,
        }
    )
    event = ConversionEvent(
        record_id=record.record_id,
        event_type="Follow-Up Scheduled",
        from_stage=record.stage.value,
        to_stage=record.stage.value,
        actor=actor,
        notes=notes or f"{next_action.strip()} due {due.isoformat()}",
        occurred_at=current,
    )
    return _replace_record(ledger, updated, event)


def recommended_action_for_stage(stage: ConversionStage) -> str:
    return default_next_action(stage)


def _record_priority(
    record: ConversionRecord,
    buyer: BuyerProfile | None,
    property_record: OwnerFinanceProperty | None,
    *,
    now: datetime,
) -> tuple[ConversionPriority, int, int, str, str]:
    if record.stage in TERMINAL_STAGES:
        return ConversionPriority.CLOSED, 0, 0, default_next_action(record.stage), "The record is closed."
    channels, contact_block = contact_permissions(buyer)
    days_idle = max(0, int((now - _current(record.last_activity_at)).total_seconds() // 86400))
    overdue_days = 0
    if record.next_action_at is not None and now > _current(record.next_action_at):
        overdue_days = max(1, int((now - _current(record.next_action_at)).total_seconds() // 86400) + 1)
    if property_record is not None and property_record.status == PropertyStatus.SOLD:
        return (
            ConversionPriority.URGENT,
            days_idle,
            overdue_days,
            "Stop property-specific follow-up and reassign the buyer to another available home.",
            "The property is marked Sold while this conversion record is still active.",
        )
    if contact_block:
        return (
            ConversionPriority.COMPLIANCE_HOLD,
            days_idle,
            overdue_days,
            "Do not contact. Review consent or close the record without sending outreach.",
            contact_block,
        )
    stall_hours = STAGE_STALL_HOURS.get(record.stage, 72)
    idle_hours = max(0, int((now - _current(record.last_activity_at)).total_seconds() // 3600))
    if overdue_days >= 2 or idle_hours >= stall_hours * 2:
        return (
            ConversionPriority.URGENT,
            days_idle,
            overdue_days,
            recommended_action_for_stage(record.stage),
            "The next action is materially overdue or the buyer has been idle too long.",
        )
    if overdue_days >= 1 or idle_hours >= stall_hours:
        return (
            ConversionPriority.HIGH,
            days_idle,
            overdue_days,
            recommended_action_for_stage(record.stage),
            "Follow-up is due or the current stage is becoming stale.",
        )
    if record.stage == ConversionStage.PAUSED:
        return (
            ConversionPriority.NURTURE,
            days_idle,
            overdue_days,
            recommended_action_for_stage(record.stage),
            "The record is paused and should be reviewed on its scheduled date.",
        )
    return (
        ConversionPriority.NORMAL,
        days_idle,
        overdue_days,
        recommended_action_for_stage(record.stage),
        "The record is active and inside its current follow-up window.",
    )


def build_conversion_queue(
    ledger: BuyerConversionLedger,
    buyers: Sequence[BuyerProfile],
    properties: Sequence[OwnerFinanceProperty],
    *,
    now: datetime | None = None,
    owner: str = "",
    include_closed: bool = False,
) -> list[ConversionQueueItem]:
    current = _current(now)
    buyers_by_id = {str(buyer.buyer_id): buyer for buyer in buyers}
    properties_by_id = {str(item.property_id): item for item in properties}
    rows: list[ConversionQueueItem] = []
    for record in ledger.records:
        if not include_closed and record.stage in TERMINAL_STAGES:
            continue
        if owner and record.owner.casefold() != owner.casefold():
            continue
        buyer = buyers_by_id.get(record.buyer_id)
        property_record = properties_by_id.get(record.property_id)
        priority, days_idle, overdue_days, recommendation, reason = _record_priority(
            record,
            buyer,
            property_record,
            now=current,
        )
        channels, contact_block = contact_permissions(buyer)
        rows.append(
            ConversionQueueItem(
                record_id=record.record_id,
                priority=priority,
                stage=record.stage,
                buyer_name=_buyer_name(buyer, record.buyer_id),
                property_address=_property_address(property_record, record.property_id),
                property_status=property_record.status.value if property_record else "Missing",
                owner=record.owner,
                days_idle=days_idle,
                overdue_days=overdue_days,
                next_action=record.next_action,
                next_action_at=record.next_action_at,
                recommended_action=recommendation,
                reason=reason,
                contact_channels=channels,
                contact_block=contact_block,
                contact_attempts=record.contact_attempts,
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            PRIORITY_SORT[row.priority],
            row.next_action_at or datetime.max.replace(tzinfo=UTC),
            row.buyer_name.casefold(),
        ),
    )


def build_funnel_snapshot(
    ledger: BuyerConversionLedger,
    buyers: Sequence[BuyerProfile],
    properties: Sequence[OwnerFinanceProperty],
    *,
    now: datetime | None = None,
) -> FunnelSnapshot:
    queue = build_conversion_queue(ledger, buyers, properties, now=now)
    total = len(ledger.records)
    active = sum(record.stage not in TERMINAL_STAGES for record in ledger.records)
    overdue = sum(item.overdue_days > 0 for item in queue)
    holds = sum(item.priority == ConversionPriority.COMPLIANCE_HOLD for item in queue)
    applications = sum(record.stage in APPLICATION_STAGES for record in ledger.records)
    showings = sum(record.stage in SHOWING_STAGES for record in ledger.records)
    contracts = sum(record.stage in CONTRACT_STAGES for record in ledger.records)
    filled = sum(record.stage == ConversionStage.FILLED for record in ledger.records)
    eligible_denominator = max(1, total - sum(record.stage == ConversionStage.LOST for record in ledger.records))
    return FunnelSnapshot(
        total_records=total,
        active_records=active,
        overdue_records=overdue,
        compliance_holds=holds,
        new_leads=sum(record.stage == ConversionStage.NEW_LEAD for record in ledger.records),
        contacted=sum(record.stage == ConversionStage.CONTACTED for record in ledger.records),
        qualified=sum(record.stage == ConversionStage.QUALIFIED for record in ledger.records),
        applications=applications,
        showings=showings,
        approved=sum(record.stage == ConversionStage.APPROVED for record in ledger.records),
        contracts=contracts,
        filled=filled,
        lost=sum(record.stage == ConversionStage.LOST for record in ledger.records),
        application_rate=applications / eligible_denominator,
        fill_rate=filled / max(1, total),
    )


def build_property_pipeline(
    ledger: BuyerConversionLedger,
    buyers: Sequence[BuyerProfile],
    properties: Sequence[OwnerFinanceProperty],
    *,
    now: datetime | None = None,
) -> list[PropertyPipelineSummary]:
    queue = build_conversion_queue(ledger, buyers, properties, now=now, include_closed=True)
    queue_by_record = {item.record_id: item for item in queue}
    properties_by_id = {str(item.property_id): item for item in properties}
    property_ids = sorted({record.property_id for record in ledger.records})
    summaries: list[PropertyPipelineSummary] = []
    for property_id in property_ids:
        records = [record for record in ledger.records if record.property_id == property_id]
        property_record = properties_by_id.get(property_id)
        summaries.append(
            PropertyPipelineSummary(
                property_id=property_id,
                property_address=_property_address(property_record, property_id),
                property_status=property_record.status.value if property_record else "Missing",
                active_buyers=sum(record.stage not in TERMINAL_STAGES for record in records),
                overdue_buyers=sum(queue_by_record[record.record_id].overdue_days > 0 for record in records),
                applications=sum(record.stage in APPLICATION_STAGES for record in records),
                showings=sum(record.stage in SHOWING_STAGES for record in records),
                approvals=sum(record.stage == ConversionStage.APPROVED for record in records),
                contracts=sum(record.stage in CONTRACT_STAGES for record in records),
                filled=sum(record.stage == ConversionStage.FILLED for record in records),
                lost=sum(record.stage == ConversionStage.LOST for record in records),
            )
        )
    return sorted(summaries, key=lambda row: (-row.active_buyers, -row.overdue_buyers, row.property_address.casefold()))


def queue_rows(items: Sequence[ConversionQueueItem]) -> list[dict[str, str | int]]:
    return [
        {
            "Priority": item.priority.value,
            "Buyer": item.buyer_name,
            "Property": item.property_address,
            "Stage": item.stage.value,
            "Owner": item.owner,
            "Due": item.next_action_at.astimezone().strftime("%Y-%m-%d %I:%M %p") if item.next_action_at else "—",
            "Overdue Days": item.overdue_days,
            "Days Idle": item.days_idle,
            "Permitted Contact": ", ".join(item.contact_channels) or "None",
            "Next Action": item.next_action or item.recommended_action,
            "Reason": item.reason,
        }
        for item in items
    ]


def property_pipeline_rows(items: Sequence[PropertyPipelineSummary]) -> list[dict[str, str | int]]:
    return [
        {
            "Property": item.property_address,
            "Status": item.property_status,
            "Active Buyers": item.active_buyers,
            "Overdue": item.overdue_buyers,
            "Applications": item.applications,
            "Showings": item.showings,
            "Approved": item.approvals,
            "Contract Pending / Filled": item.contracts,
            "Lost": item.lost,
        }
        for item in items
    ]


def event_rows(
    ledger: BuyerConversionLedger,
    buyers: Sequence[BuyerProfile],
    properties: Sequence[OwnerFinanceProperty],
) -> list[dict[str, str]]:
    records = {record.record_id: record for record in ledger.records}
    buyers_by_id = {str(buyer.buyer_id): buyer for buyer in buyers}
    properties_by_id = {str(item.property_id): item for item in properties}
    rows: list[dict[str, str]] = []
    for event in sorted(ledger.events, key=lambda item: item.occurred_at, reverse=True):
        record = records.get(event.record_id)
        buyer = buyers_by_id.get(record.buyer_id) if record else None
        property_record = properties_by_id.get(record.property_id) if record else None
        rows.append(
            {
                "When": event.occurred_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Buyer": _buyer_name(buyer, record.buyer_id if record else "missing"),
                "Property": _property_address(property_record, record.property_id if record else "missing"),
                "Event": event.event_type,
                "From": event.from_stage or "—",
                "To": event.to_stage or "—",
                "Actor": event.actor or "—",
                "Notes": event.notes or "—",
            }
        )
    return rows


class BuyerConversionStore:
    """Private Supabase Storage ledger for buyer conversion pipeline records."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise BuyerConversionError("Supabase is not configured for buyer conversion records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise BuyerConversionError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(BUYER_CONVERSION_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    BUYER_CONVERSION_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": BUYER_CONVERSION_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise BuyerConversionError("Could not create the private buyer conversion bucket.") from exc
        self._bucket_ready = True

    def load(self) -> BuyerConversionLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(BUYER_CONVERSION_BUCKET).download(BUYER_CONVERSION_PATH)
        except Exception:
            return BuyerConversionLedger()
        try:
            payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
            return BuyerConversionLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BuyerConversionError("The saved buyer conversion ledger could not be read.") from exc

    def save(self, ledger: BuyerConversionLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > BUYER_CONVERSION_MAX_BYTES:
            raise BuyerConversionError("The buyer conversion ledger is too large to save.")
        try:
            self._client.storage.from_(BUYER_CONVERSION_BUCKET).upload(
                path=BUYER_CONVERSION_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise BuyerConversionError("Could not save buyer conversion records.") from exc
