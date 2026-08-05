from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .buyer_conversion import (
    ActivityType,
    BuyerConversionError,
    BuyerConversionLedger,
    ConversionRecord,
    ConversionStage,
    TERMINAL_STAGES,
    record_activity,
    schedule_follow_up,
    transition_record,
)
from .models import BuyerProfile, OwnerFinanceProperty, PropertyStatus
from .storage import SupabaseSettings

SHOWING_BUCKET = "cfh-showing-conversion"
SHOWING_PATH = "showing-conversion/ledger.json"
SHOWING_MAX_BYTES = 4 * 1024 * 1024


class ShowingConversionError(RuntimeError):
    """Raised when a showing workflow operation cannot be completed safely."""


class ShowingStatus(StrEnum):
    SCHEDULED = "Scheduled"
    CONFIRMED = "Confirmed"
    ATTENDED = "Attended"
    NO_SHOW = "No Show"
    RESCHEDULE_REQUESTED = "Reschedule Requested"
    CANCELLED = "Cancelled"
    CONTRACT_HANDOFF = "Contract Handoff"
    CLOSED_LOST = "Closed / Lost"


class ShowingDecision(StrEnum):
    UNDECIDED = "Undecided"
    INTERESTED = "Interested"
    NEEDS_FOLLOW_UP = "Needs Follow-Up"
    REQUESTED_TERMS_REVIEW = "Requested Terms Review"
    READY_FOR_CONTRACT = "Ready for Contract"
    NOT_INTERESTED = "Not Interested"


class ObjectionCategory(StrEnum):
    NONE = "No Objection Recorded"
    TOTAL_PRICE = "Total Price"
    DOWN_PAYMENT = "Down Payment"
    MONTHLY_PAYMENT = "Monthly Payment"
    INTEREST_OR_TERM = "Interest Rate or Term"
    CONDITION_REPAIRS = "Condition or Repairs"
    LOCATION = "Location"
    TIMING = "Move Timing"
    APPLICATION_PROCESS = "Application Process"
    FINANCING = "Financing or Approval"
    DECISION_MAKER = "Needs Another Decision-Maker"
    ACCESS = "Showing Access"
    OTHER = "Other"


class ReminderType(StrEnum):
    CONFIRMATION = "Showing Confirmation"
    DAY_BEFORE = "24-Hour Reminder"
    TWO_HOUR = "2-Hour Reminder"
    NO_SHOW_RECOVERY = "No-Show Recovery"
    POST_SHOWING = "Post-Showing Follow-Up"


class ReminderStatus(StrEnum):
    READY = "Ready"
    APPROVED = "Approved"
    SENT_MANUALLY = "Sent Manually"
    SKIPPED = "Skipped"
    FAILED = "Failed"


class ShowingPriority(StrEnum):
    URGENT = "Urgent"
    HIGH = "High"
    NORMAL = "Normal"
    NURTURE = "Nurture"
    CLOSED = "Closed"
    COMPLIANCE_HOLD = "Compliance Hold"


PRIORITY_SORT = {
    ShowingPriority.COMPLIANCE_HOLD: 0,
    ShowingPriority.URGENT: 1,
    ShowingPriority.HIGH: 2,
    ShowingPriority.NORMAL: 3,
    ShowingPriority.NURTURE: 4,
    ShowingPriority.CLOSED: 5,
}

ACTIVE_SHOWING_STATUSES = {
    ShowingStatus.SCHEDULED,
    ShowingStatus.CONFIRMED,
    ShowingStatus.RESCHEDULE_REQUESTED,
    ShowingStatus.NO_SHOW,
    ShowingStatus.ATTENDED,
    ShowingStatus.CONTRACT_HANDOFF,
}

CLOSED_SHOWING_STATUSES = {
    ShowingStatus.CANCELLED,
    ShowingStatus.CLOSED_LOST,
}

STAGE_RANK = {
    ConversionStage.NEW_LEAD: 1,
    ConversionStage.CONTACTED: 2,
    ConversionStage.QUALIFIED: 3,
    ConversionStage.APPLICATION_STARTED: 4,
    ConversionStage.APPLICATION_SUBMITTED: 5,
    ConversionStage.SHOWING_SCHEDULED: 6,
    ConversionStage.SHOWING_COMPLETED: 7,
    ConversionStage.APPROVED: 8,
    ConversionStage.CONTRACT_PENDING: 9,
    ConversionStage.FILLED: 10,
    ConversionStage.PAUSED: 0,
    ConversionStage.LOST: 0,
}


class ShowingReminder(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reminder_id: str = Field(default_factory=lambda: str(uuid4()))
    appointment_id: str
    reminder_type: ReminderType
    channel: str = Field(min_length=2, max_length=40)
    scheduled_for: datetime
    message: str = Field(min_length=10, max_length=2500)
    status: ReminderStatus = ReminderStatus.READY
    approved_by: str = Field(default="", max_length=120)
    approved_at: datetime | None = None
    sent_at: datetime | None = None
    notes: str = Field(default="", max_length=1200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ShowingAppointment(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    appointment_id: str = Field(default_factory=lambda: str(uuid4()))
    conversion_record_id: str
    buyer_id: str
    property_id: str
    scheduled_at: datetime
    duration_minutes: int = Field(default=30, ge=10, le=240)
    status: ShowingStatus = ShowingStatus.SCHEDULED
    owner: str = Field(default="Sabrina", max_length=120)
    access_method: str = Field(default="Team-coordinated access", max_length=300)
    buyer_instructions: str = Field(default="", max_length=1200)
    internal_access_notes: str = Field(default="", max_length=2000)
    confirmation_required: bool = True
    confirmed_at: datetime | None = None
    attended_at: datetime | None = None
    completed_at: datetime | None = None
    reschedule_count: int = Field(default=0, ge=0, le=100)
    cancellation_reason: str = Field(default="", max_length=1200)
    decision: ShowingDecision = ShowingDecision.UNDECIDED
    objection_category: ObjectionCategory = ObjectionCategory.NONE
    objection_notes: str = Field(default="", max_length=2000)
    feedback_summary: str = Field(default="", max_length=3000)
    next_action: str = Field(default="Confirm the showing and access plan.", max_length=1200)
    next_action_at: datetime | None = None
    contract_handoff_by: str = Field(default="", max_length=120)
    contract_handoff_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_decision_details(self) -> ShowingAppointment:
        if self.decision == ShowingDecision.NOT_INTERESTED and not self.feedback_summary:
            raise ValueError("Feedback is required when a buyer is marked Not Interested")
        if self.objection_category != ObjectionCategory.NONE and not self.objection_notes:
            raise ValueError("Objection notes are required when an objection category is selected")
        return self


class ShowingEvent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    appointment_id: str
    event_type: str = Field(min_length=2, max_length=160)
    from_status: str = ""
    to_status: str = ""
    actor: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2500)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ShowingConversionLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    appointments: list[ShowingAppointment] = Field(default_factory=list)
    reminders: list[ShowingReminder] = Field(default_factory=list)
    events: list[ShowingEvent] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ShowingQueueItem:
    appointment_id: str
    priority: ShowingPriority
    status: ShowingStatus
    buyer_name: str
    property_address: str
    owner: str
    scheduled_at: datetime
    minutes_until_showing: int
    next_action: str
    next_action_at: datetime | None
    recommended_action: str
    reason: str
    contact_channels: tuple[str, ...]
    contact_block: str
    decision: ShowingDecision
    objection_category: ObjectionCategory


@dataclass(frozen=True, slots=True)
class ShowingFunnelSnapshot:
    total: int
    scheduled: int
    confirmed: int
    attended: int
    no_shows: int
    cancelled: int
    contract_handoffs: int
    closed_lost: int
    confirmation_rate: float
    show_rate: float
    no_show_rate: float
    showing_to_contract_rate: float


@dataclass(frozen=True, slots=True)
class PropertyObjectionSummary:
    property_id: str
    property_address: str
    attended_showings: int
    contract_handoffs: int
    top_objection: str
    objection_count: int
    objection_breakdown: str
    conversion_rate: float


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def _find_conversion_record(
    ledger: BuyerConversionLedger,
    record_id: str,
) -> ConversionRecord:
    record = next((item for item in ledger.records if item.record_id == record_id), None)
    if record is None:
        raise ShowingConversionError("The selected buyer conversion record could not be found.")
    return record


def find_appointment(
    ledger: ShowingConversionLedger,
    appointment_id: str,
) -> ShowingAppointment | None:
    return next((item for item in ledger.appointments if item.appointment_id == appointment_id), None)


def _replace_appointment(
    ledger: ShowingConversionLedger,
    updated: ShowingAppointment,
    *,
    event_type: str,
    actor: str,
    notes: str = "",
    previous_status: ShowingStatus | None = None,
    reminders: Sequence[ShowingReminder] | None = None,
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    event = ShowingEvent(
        appointment_id=updated.appointment_id,
        event_type=event_type,
        from_status=(previous_status.value if previous_status else updated.status.value),
        to_status=updated.status.value,
        actor=actor,
        notes=notes,
        occurred_at=current,
    )
    appointments = [
        updated if item.appointment_id == updated.appointment_id else item
        for item in ledger.appointments
    ]
    return ledger.model_copy(
        update={
            "appointments": appointments,
            "reminders": list(reminders) if reminders is not None else ledger.reminders,
            "events": [*ledger.events, event],
            "updated_at": current,
        }
    )


def contact_permissions(buyer: BuyerProfile | None) -> tuple[tuple[str, ...], str]:
    if buyer is None:
        return (), "Buyer record is missing."
    if buyer.do_not_contact:
        return (), "Buyer is marked Do Not Contact."
    channels: list[str] = []
    if buyer.sms_consent and buyer.phone:
        channels.append("SMS")
    if buyer.email_consent and buyer.email:
        channels.append("Email")
    if buyer.call_consent and buyer.phone:
        channels.append("Phone")
    if not channels:
        return (), "No saved contact consent is available."
    return tuple(channels), ""


def preferred_reminder_channel(buyer: BuyerProfile | None) -> str | None:
    channels, _ = contact_permissions(buyer)
    if not channels:
        return None
    preference = buyer.communication_preference.value if buyer else "Any"
    if preference in channels:
        return preference
    for channel in ("SMS", "Email", "Phone"):
        if channel in channels:
            return channel
    return channels[0]


def _display_time(value: datetime) -> str:
    return value.astimezone().strftime("%A, %B %d at %I:%M %p")


def reminder_message(
    reminder_type: ReminderType,
    *,
    property_address: str,
    scheduled_at: datetime,
    buyer_instructions: str = "",
) -> str:
    time_text = _display_time(scheduled_at)
    instructions = (
        f" Approved showing instructions: {buyer_instructions.strip()}"
        if buyer_instructions.strip()
        else ""
    )
    if reminder_type == ReminderType.CONFIRMATION:
        return (
            f"Your showing for {property_address} is scheduled for {time_text}."
            f"{instructions} Please confirm or contact the team if you need to reschedule."
        )
    if reminder_type == ReminderType.DAY_BEFORE:
        return (
            f"Reminder: your showing for {property_address} is tomorrow at {time_text}."
            f"{instructions} Please confirm that the time still works."
        )
    if reminder_type == ReminderType.TWO_HOUR:
        return (
            f"Your showing for {property_address} is in about two hours at {time_text}."
            f"{instructions} Contact the team now if your arrival time changed."
        )
    if reminder_type == ReminderType.NO_SHOW_RECOVERY:
        return (
            f"We missed you at the scheduled showing for {property_address}. "
            "Reply through your normal contact method if you still want to see the home, "
            "and the team will offer another available time."
        )
    return (
        f"Thank you for viewing {property_address}. Please share your decision, questions, "
        "or the main issue preventing you from moving forward."
    )


def build_showing_reminders(
    appointment: ShowingAppointment,
    buyer: BuyerProfile | None,
    property_record: OwnerFinanceProperty,
    *,
    now: datetime | None = None,
) -> list[ShowingReminder]:
    current = _current(now)
    channel = preferred_reminder_channel(buyer)
    if channel is None:
        return []
    schedule: list[tuple[ReminderType, datetime]] = [
        (ReminderType.CONFIRMATION, current),
    ]
    day_before = appointment.scheduled_at - timedelta(hours=24)
    two_hour = appointment.scheduled_at - timedelta(hours=2)
    if day_before > current:
        schedule.append((ReminderType.DAY_BEFORE, day_before))
    if two_hour > current:
        schedule.append((ReminderType.TWO_HOUR, two_hour))
    return [
        ShowingReminder(
            appointment_id=appointment.appointment_id,
            reminder_type=reminder_type,
            channel=channel,
            scheduled_for=scheduled_for,
            message=reminder_message(
                reminder_type,
                property_address=property_record.display_address,
                scheduled_at=appointment.scheduled_at,
                buyer_instructions=appointment.buyer_instructions,
            ),
            created_at=current,
            updated_at=current,
        )
        for reminder_type, scheduled_for in schedule
    ]


def create_appointment(
    ledger: ShowingConversionLedger,
    conversion_ledger: BuyerConversionLedger,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    *,
    conversion_record_id: str,
    scheduled_at: datetime,
    owner: str,
    duration_minutes: int = 30,
    access_method: str = "Team-coordinated access",
    buyer_instructions: str = "",
    internal_access_notes: str = "",
    now: datetime | None = None,
) -> tuple[ShowingConversionLedger, ShowingAppointment]:
    current = _current(now)
    showing_time = _current(scheduled_at)
    if showing_time <= current:
        raise ShowingConversionError("Schedule the showing for a future date and time.")
    record = _find_conversion_record(conversion_ledger, conversion_record_id)
    if record.stage in TERMINAL_STAGES:
        raise ShowingConversionError("A closed buyer conversion record cannot receive a showing.")
    if record.buyer_id != str(buyer.buyer_id) or record.property_id != str(property_record.property_id):
        raise ShowingConversionError("The buyer, property, and conversion record do not match.")
    if property_record.status in {PropertyStatus.SOLD, PropertyStatus.FILLED, PropertyStatus.PAUSED}:
        raise ShowingConversionError("This property is not currently available for a new showing.")
    duplicate = next(
        (
            item
            for item in ledger.appointments
            if item.conversion_record_id == conversion_record_id
            and item.status in ACTIVE_SHOWING_STATUSES
        ),
        None,
    )
    if duplicate:
        raise ShowingConversionError("An active showing already exists for this buyer and property.")
    appointment = ShowingAppointment(
        conversion_record_id=conversion_record_id,
        buyer_id=str(buyer.buyer_id),
        property_id=str(property_record.property_id),
        scheduled_at=showing_time,
        duration_minutes=duration_minutes,
        owner=owner or "Unassigned",
        access_method=access_method,
        buyer_instructions=buyer_instructions,
        internal_access_notes=internal_access_notes,
        next_action="Confirm the buyer, access plan, and arrival instructions.",
        next_action_at=min(showing_time - timedelta(hours=24), current + timedelta(hours=2)),
        created_at=current,
        updated_at=current,
    )
    reminders = build_showing_reminders(appointment, buyer, property_record, now=current)
    event = ShowingEvent(
        appointment_id=appointment.appointment_id,
        event_type="Showing Scheduled",
        to_status=appointment.status.value,
        actor=owner,
        notes=f"Showing scheduled for {showing_time.isoformat()}.",
        occurred_at=current,
    )
    updated = ledger.model_copy(
        update={
            "appointments": [*ledger.appointments, appointment],
            "reminders": [*ledger.reminders, *reminders],
            "events": [*ledger.events, event],
            "updated_at": current,
        }
    )
    return updated, appointment


def confirm_appointment(
    ledger: ShowingConversionLedger,
    *,
    appointment_id: str,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    appointment = find_appointment(ledger, appointment_id)
    if appointment is None:
        raise ShowingConversionError("The selected showing could not be found.")
    if appointment.status not in {ShowingStatus.SCHEDULED, ShowingStatus.RESCHEDULE_REQUESTED}:
        raise ShowingConversionError("Only a scheduled or reschedule-requested showing can be confirmed.")
    previous = appointment.status
    updated = appointment.model_copy(
        update={
            "status": ShowingStatus.CONFIRMED,
            "confirmed_at": current,
            "next_action": "Complete the showing and record the buyer outcome immediately afterward.",
            "next_action_at": appointment.scheduled_at + timedelta(hours=1),
            "updated_at": current,
        }
    )
    return _replace_appointment(
        ledger,
        updated,
        event_type="Showing Confirmed",
        actor=actor,
        notes=notes,
        previous_status=previous,
        now=current,
    )


def _skip_open_reminders(
    reminders: Sequence[ShowingReminder],
    appointment_id: str,
    *,
    reason: str,
    now: datetime,
) -> list[ShowingReminder]:
    return [
        reminder.model_copy(
            update={
                "status": ReminderStatus.SKIPPED,
                "notes": reason,
                "updated_at": now,
            }
        )
        if reminder.appointment_id == appointment_id
        and reminder.status in {ReminderStatus.READY, ReminderStatus.APPROVED}
        else reminder
        for reminder in reminders
    ]


def reschedule_appointment(
    ledger: ShowingConversionLedger,
    buyer: BuyerProfile | None,
    property_record: OwnerFinanceProperty,
    *,
    appointment_id: str,
    new_scheduled_at: datetime,
    actor: str,
    reason: str,
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    new_time = _current(new_scheduled_at)
    if new_time <= current:
        raise ShowingConversionError("The new showing time must be in the future.")
    appointment = find_appointment(ledger, appointment_id)
    if appointment is None:
        raise ShowingConversionError("The selected showing could not be found.")
    if appointment.status in CLOSED_SHOWING_STATUSES | {ShowingStatus.CONTRACT_HANDOFF}:
        raise ShowingConversionError("A closed or contract-handoff showing cannot be rescheduled.")
    previous = appointment.status
    updated = appointment.model_copy(
        update={
            "scheduled_at": new_time,
            "status": ShowingStatus.SCHEDULED,
            "confirmed_at": None,
            "reschedule_count": appointment.reschedule_count + 1,
            "next_action": "Confirm the revised showing time and access plan.",
            "next_action_at": min(new_time - timedelta(hours=24), current + timedelta(hours=2)),
            "updated_at": current,
        }
    )
    reminders = _skip_open_reminders(
        ledger.reminders,
        appointment_id,
        reason="Skipped because the showing was rescheduled.",
        now=current,
    )
    reminders.extend(build_showing_reminders(updated, buyer, property_record, now=current))
    return _replace_appointment(
        ledger,
        updated,
        event_type="Showing Rescheduled",
        actor=actor,
        notes=reason,
        previous_status=previous,
        reminders=reminders,
        now=current,
    )


def record_no_show(
    ledger: ShowingConversionLedger,
    buyer: BuyerProfile | None,
    property_record: OwnerFinanceProperty,
    *,
    appointment_id: str,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    appointment = find_appointment(ledger, appointment_id)
    if appointment is None:
        raise ShowingConversionError("The selected showing could not be found.")
    if appointment.status not in {ShowingStatus.SCHEDULED, ShowingStatus.CONFIRMED}:
        raise ShowingConversionError("Only a scheduled or confirmed showing can be marked No Show.")
    previous = appointment.status
    updated = appointment.model_copy(
        update={
            "status": ShowingStatus.NO_SHOW,
            "decision": ShowingDecision.NEEDS_FOLLOW_UP,
            "next_action": "Contact the buyer through a permitted channel and offer another available showing time.",
            "next_action_at": current + timedelta(minutes=15),
            "updated_at": current,
        }
    )
    reminders = _skip_open_reminders(
        ledger.reminders,
        appointment_id,
        reason="Skipped because the scheduled showing time passed.",
        now=current,
    )
    channel = preferred_reminder_channel(buyer)
    if channel:
        reminders.append(
            ShowingReminder(
                appointment_id=appointment_id,
                reminder_type=ReminderType.NO_SHOW_RECOVERY,
                channel=channel,
                scheduled_for=current,
                message=reminder_message(
                    ReminderType.NO_SHOW_RECOVERY,
                    property_address=property_record.display_address,
                    scheduled_at=appointment.scheduled_at,
                ),
                created_at=current,
                updated_at=current,
            )
        )
    return _replace_appointment(
        ledger,
        updated,
        event_type="No Show Recorded",
        actor=actor,
        notes=notes,
        previous_status=previous,
        reminders=reminders,
        now=current,
    )


def record_attendance_outcome(
    ledger: ShowingConversionLedger,
    buyer: BuyerProfile | None,
    property_record: OwnerFinanceProperty,
    *,
    appointment_id: str,
    actor: str,
    decision: ShowingDecision,
    objection_category: ObjectionCategory = ObjectionCategory.NONE,
    objection_notes: str = "",
    feedback_summary: str = "",
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    appointment = find_appointment(ledger, appointment_id)
    if appointment is None:
        raise ShowingConversionError("The selected showing could not be found.")
    if appointment.status not in {ShowingStatus.SCHEDULED, ShowingStatus.CONFIRMED, ShowingStatus.ATTENDED}:
        raise ShowingConversionError("This showing cannot receive an attendance outcome from its current status.")
    if decision == ShowingDecision.UNDECIDED:
        raise ShowingConversionError("Choose the buyer's current decision before saving the showing outcome.")
    if decision == ShowingDecision.NOT_INTERESTED and not feedback_summary.strip():
        raise ShowingConversionError("Record why the buyer is not interested.")
    if objection_category != ObjectionCategory.NONE and not objection_notes.strip():
        raise ShowingConversionError("Add notes describing the selected objection.")
    previous = appointment.status
    contract_handoff = decision == ShowingDecision.READY_FOR_CONTRACT
    closed_lost = decision == ShowingDecision.NOT_INTERESTED
    status = (
        ShowingStatus.CONTRACT_HANDOFF
        if contract_handoff
        else ShowingStatus.CLOSED_LOST
        if closed_lost
        else ShowingStatus.ATTENDED
    )
    if contract_handoff:
        next_action = "Prepare the contract package and confirm required funds, signatures, and documents."
        next_due = current + timedelta(hours=2)
    elif closed_lost:
        next_action = ""
        next_due = None
    elif decision == ShowingDecision.REQUESTED_TERMS_REVIEW:
        next_action = "Escalate the exact objection for management review without promising a terms change."
        next_due = current + timedelta(hours=4)
    else:
        next_action = "Follow up on the showing decision and move the buyer toward approval, contract, or a documented loss."
        next_due = current + timedelta(hours=12)
    updated = appointment.model_copy(
        update={
            "status": status,
            "attended_at": appointment.attended_at or current,
            "completed_at": current if status in {ShowingStatus.CONTRACT_HANDOFF, ShowingStatus.CLOSED_LOST} else None,
            "decision": decision,
            "objection_category": objection_category,
            "objection_notes": objection_notes,
            "feedback_summary": feedback_summary,
            "next_action": next_action,
            "next_action_at": next_due,
            "contract_handoff_by": actor if contract_handoff else "",
            "contract_handoff_at": current if contract_handoff else None,
            "updated_at": current,
        }
    )
    reminders = _skip_open_reminders(
        ledger.reminders,
        appointment_id,
        reason="Skipped because the showing outcome was recorded.",
        now=current,
    )
    channel = preferred_reminder_channel(buyer)
    if channel and not closed_lost and not contract_handoff:
        reminders.append(
            ShowingReminder(
                appointment_id=appointment_id,
                reminder_type=ReminderType.POST_SHOWING,
                channel=channel,
                scheduled_for=current,
                message=reminder_message(
                    ReminderType.POST_SHOWING,
                    property_address=property_record.display_address,
                    scheduled_at=appointment.scheduled_at,
                ),
                created_at=current,
                updated_at=current,
            )
        )
    return _replace_appointment(
        ledger,
        updated,
        event_type="Showing Outcome Recorded",
        actor=actor,
        notes=feedback_summary or objection_notes,
        previous_status=previous,
        reminders=reminders,
        now=current,
    )


def cancel_appointment(
    ledger: ShowingConversionLedger,
    *,
    appointment_id: str,
    actor: str,
    reason: str,
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    if not reason.strip():
        raise ShowingConversionError("Enter the cancellation reason.")
    appointment = find_appointment(ledger, appointment_id)
    if appointment is None:
        raise ShowingConversionError("The selected showing could not be found.")
    if appointment.status in CLOSED_SHOWING_STATUSES | {ShowingStatus.CONTRACT_HANDOFF}:
        raise ShowingConversionError("This showing is already closed.")
    previous = appointment.status
    updated = appointment.model_copy(
        update={
            "status": ShowingStatus.CANCELLED,
            "cancellation_reason": reason,
            "completed_at": current,
            "next_action": "",
            "next_action_at": None,
            "updated_at": current,
        }
    )
    reminders = _skip_open_reminders(
        ledger.reminders,
        appointment_id,
        reason="Skipped because the showing was cancelled.",
        now=current,
    )
    return _replace_appointment(
        ledger,
        updated,
        event_type="Showing Cancelled",
        actor=actor,
        notes=reason,
        previous_status=previous,
        reminders=reminders,
        now=current,
    )


def update_reminder(
    ledger: ShowingConversionLedger,
    *,
    reminder_id: str,
    status: ReminderStatus,
    actor: str,
    notes: str = "",
    now: datetime | None = None,
) -> ShowingConversionLedger:
    current = _current(now)
    reminder = next((item for item in ledger.reminders if item.reminder_id == reminder_id), None)
    if reminder is None:
        raise ShowingConversionError("The selected reminder could not be found.")
    if reminder.status in {ReminderStatus.SENT_MANUALLY, ReminderStatus.SKIPPED}:
        raise ShowingConversionError("A sent or skipped reminder cannot be changed.")
    updated = reminder.model_copy(
        update={
            "status": status,
            "approved_by": actor if status == ReminderStatus.APPROVED else reminder.approved_by,
            "approved_at": current if status == ReminderStatus.APPROVED else reminder.approved_at,
            "sent_at": current if status == ReminderStatus.SENT_MANUALLY else reminder.sent_at,
            "notes": notes,
            "updated_at": current,
        }
    )
    reminders = [updated if item.reminder_id == reminder_id else item for item in ledger.reminders]
    event = ShowingEvent(
        appointment_id=reminder.appointment_id,
        event_type=f"Reminder {status.value}",
        actor=actor,
        notes=notes or reminder.reminder_type.value,
        occurred_at=current,
    )
    return ledger.model_copy(
        update={
            "reminders": reminders,
            "events": [*ledger.events, event],
            "updated_at": current,
        }
    )


def sync_conversion_for_scheduled_showing(
    ledger: BuyerConversionLedger,
    appointment: ShowingAppointment,
    *,
    actor: str,
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    record = _find_conversion_record(ledger, appointment.conversion_record_id)
    if record.stage in TERMINAL_STAGES:
        raise ShowingConversionError("The buyer conversion record is closed.")
    due = min(appointment.scheduled_at - timedelta(hours=24), current + timedelta(hours=2))
    action = "Confirm the showing and approved access instructions."
    try:
        if STAGE_RANK[record.stage] < STAGE_RANK[ConversionStage.SHOWING_SCHEDULED]:
            return transition_record(
                ledger,
                record_id=record.record_id,
                new_stage=ConversionStage.SHOWING_SCHEDULED,
                actor=actor,
                notes=f"Showing scheduled for {appointment.scheduled_at.isoformat()}.",
                next_action=action,
                next_action_at=due,
                now=current,
            )
        return schedule_follow_up(
            ledger,
            record_id=record.record_id,
            next_action=action,
            next_action_at=due,
            actor=actor,
            notes=f"Showing scheduled for {appointment.scheduled_at.isoformat()}.",
            now=current,
        )
    except BuyerConversionError as exc:
        raise ShowingConversionError(str(exc)) from exc


def sync_conversion_for_confirmation(
    ledger: BuyerConversionLedger,
    appointment: ShowingAppointment,
    *,
    actor: str,
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    try:
        return record_activity(
            ledger,
            record_id=appointment.conversion_record_id,
            activity_type=ActivityType.SHOWING_CONFIRMED,
            actor=actor,
            notes=f"Showing confirmed for {appointment.scheduled_at.isoformat()}.",
            next_action="Complete the showing and record the buyer outcome.",
            next_action_at=appointment.scheduled_at + timedelta(hours=1),
            now=current,
        )
    except BuyerConversionError as exc:
        raise ShowingConversionError(str(exc)) from exc


def sync_conversion_for_no_show(
    ledger: BuyerConversionLedger,
    appointment: ShowingAppointment,
    *,
    actor: str,
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    try:
        return schedule_follow_up(
            ledger,
            record_id=appointment.conversion_record_id,
            next_action="Contact the buyer through a permitted channel and offer another available showing time.",
            next_action_at=current + timedelta(minutes=15),
            actor=actor,
            notes="Buyer did not attend the scheduled showing.",
            now=current,
        )
    except BuyerConversionError as exc:
        raise ShowingConversionError(str(exc)) from exc


def sync_conversion_for_outcome(
    ledger: BuyerConversionLedger,
    appointment: ShowingAppointment,
    *,
    actor: str,
    target_stage: ConversionStage,
    lost_reason: str = "",
    now: datetime | None = None,
) -> BuyerConversionLedger:
    current = _current(now)
    allowed = {
        ConversionStage.SHOWING_COMPLETED,
        ConversionStage.APPROVED,
        ConversionStage.CONTRACT_PENDING,
        ConversionStage.LOST,
    }
    if target_stage not in allowed:
        raise ShowingConversionError("Choose Showing Completed, Approved, Contract Pending, or Lost.")
    record = _find_conversion_record(ledger, appointment.conversion_record_id)
    if record.stage in TERMINAL_STAGES:
        raise ShowingConversionError("The buyer conversion record is already closed.")
    if target_stage == ConversionStage.LOST and not lost_reason.strip():
        raise ShowingConversionError("Enter the buyer's lost reason.")
    try:
        if target_stage == record.stage:
            return record_activity(
                ledger,
                record_id=record.record_id,
                activity_type=ActivityType.NOTE,
                actor=actor,
                notes=appointment.feedback_summary or appointment.objection_notes,
                now=current,
            )
        return transition_record(
            ledger,
            record_id=record.record_id,
            new_stage=target_stage,
            actor=actor,
            notes=appointment.feedback_summary or appointment.objection_notes,
            lost_reason=lost_reason,
            now=current,
        )
    except BuyerConversionError as exc:
        raise ShowingConversionError(str(exc)) from exc


def _buyer_name(buyer: BuyerProfile | None, buyer_id: str) -> str:
    if buyer is None:
        return f"Buyer {buyer_id[:8]}"
    name = " ".join(part for part in (buyer.first_name, buyer.last_name) if part).strip()
    return name or f"Buyer {buyer_id[:8]}"


def _property_address(property_record: OwnerFinanceProperty | None, property_id: str) -> str:
    if property_record is None:
        return f"Property {property_id[:8]}"
    return property_record.display_address or f"Property {property_id[:8]}"


def _queue_priority(
    appointment: ShowingAppointment,
    buyer: BuyerProfile | None,
    *,
    now: datetime,
) -> tuple[ShowingPriority, str, str]:
    _, contact_block = contact_permissions(buyer)
    if appointment.status in CLOSED_SHOWING_STATUSES:
        return ShowingPriority.CLOSED, "No further showing action is required.", "The showing is closed."
    if contact_block and appointment.status not in {ShowingStatus.CONTRACT_HANDOFF, ShowingStatus.ATTENDED}:
        return (
            ShowingPriority.COMPLIANCE_HOLD,
            "Do not send reminders. Review consent or coordinate through Dwelyx.",
            contact_block,
        )
    if appointment.status == ShowingStatus.CONTRACT_HANDOFF:
        return (
            ShowingPriority.URGENT,
            "Prepare the contract package and confirm signatures, funds, and documents.",
            "The buyer is ready for contract handoff.",
        )
    if appointment.status == ShowingStatus.NO_SHOW:
        return (
            ShowingPriority.URGENT,
            "Contact the buyer through a permitted channel and offer another available time.",
            "The buyer missed the showing and recovery is still open.",
        )
    minutes_until = int((appointment.scheduled_at - now).total_seconds() // 60)
    if appointment.status in {ShowingStatus.SCHEDULED, ShowingStatus.CONFIRMED} and minutes_until < -60:
        return (
            ShowingPriority.URGENT,
            "Record attended, no-show, cancelled, or rescheduled now.",
            "The scheduled showing time passed without an outcome.",
        )
    if appointment.status == ShowingStatus.SCHEDULED and minutes_until <= 120:
        return (
            ShowingPriority.URGENT,
            "Confirm the buyer and access plan immediately.",
            "The showing is within two hours and is not confirmed.",
        )
    if appointment.status == ShowingStatus.SCHEDULED and minutes_until <= 1440:
        return (
            ShowingPriority.HIGH,
            "Confirm the showing and approved access instructions today.",
            "The showing is within 24 hours and is not confirmed.",
        )
    if appointment.status == ShowingStatus.ATTENDED:
        due = appointment.next_action_at or appointment.attended_at or appointment.updated_at
        if now >= due:
            return (
                ShowingPriority.HIGH,
                "Get the buyer's decision and move the file to Approved, Contract Pending, or Lost.",
                "The showing occurred but the decision follow-up is due.",
            )
        return (
            ShowingPriority.NORMAL,
            "Complete the scheduled post-showing follow-up.",
            "The buyer attended and a decision is still pending.",
        )
    if appointment.status == ShowingStatus.RESCHEDULE_REQUESTED:
        return (
            ShowingPriority.HIGH,
            "Offer a new available time and save the revised appointment.",
            "The buyer requested a reschedule.",
        )
    return (
        ShowingPriority.NORMAL,
        appointment.next_action or "Review the showing status.",
        "The showing is active and inside its current action window.",
    )


def build_showing_queue(
    ledger: ShowingConversionLedger,
    buyers: Sequence[BuyerProfile],
    properties: Sequence[OwnerFinanceProperty],
    *,
    now: datetime | None = None,
    owner: str = "",
    include_closed: bool = False,
) -> list[ShowingQueueItem]:
    current = _current(now)
    buyers_by_id = {str(item.buyer_id): item for item in buyers}
    properties_by_id = {str(item.property_id): item for item in properties}
    rows: list[ShowingQueueItem] = []
    for appointment in ledger.appointments:
        if not include_closed and appointment.status in CLOSED_SHOWING_STATUSES:
            continue
        if owner and appointment.owner.casefold() != owner.casefold():
            continue
        buyer = buyers_by_id.get(appointment.buyer_id)
        property_record = properties_by_id.get(appointment.property_id)
        priority, recommendation, reason = _queue_priority(appointment, buyer, now=current)
        channels, contact_block = contact_permissions(buyer)
        minutes_until = int((appointment.scheduled_at - current).total_seconds() // 60)
        rows.append(
            ShowingQueueItem(
                appointment_id=appointment.appointment_id,
                priority=priority,
                status=appointment.status,
                buyer_name=_buyer_name(buyer, appointment.buyer_id),
                property_address=_property_address(property_record, appointment.property_id),
                owner=appointment.owner,
                scheduled_at=appointment.scheduled_at,
                minutes_until_showing=minutes_until,
                next_action=appointment.next_action,
                next_action_at=appointment.next_action_at,
                recommended_action=recommendation,
                reason=reason,
                contact_channels=channels,
                contact_block=contact_block,
                decision=appointment.decision,
                objection_category=appointment.objection_category,
            )
        )
    return sorted(
        rows,
        key=lambda item: (
            PRIORITY_SORT[item.priority],
            item.next_action_at or item.scheduled_at,
            item.buyer_name.casefold(),
        ),
    )


def build_showing_funnel(ledger: ShowingConversionLedger) -> ShowingFunnelSnapshot:
    total = len(ledger.appointments)
    scheduled = sum(item.status == ShowingStatus.SCHEDULED for item in ledger.appointments)
    confirmed = sum(
        item.confirmed_at is not None
        or item.status in {ShowingStatus.CONFIRMED, ShowingStatus.ATTENDED, ShowingStatus.CONTRACT_HANDOFF}
        for item in ledger.appointments
    )
    attended = sum(
        item.attended_at is not None
        or item.status in {ShowingStatus.ATTENDED, ShowingStatus.CONTRACT_HANDOFF}
        for item in ledger.appointments
    )
    no_shows = sum(item.status == ShowingStatus.NO_SHOW for item in ledger.appointments)
    cancelled = sum(item.status == ShowingStatus.CANCELLED for item in ledger.appointments)
    contract_handoffs = sum(item.status == ShowingStatus.CONTRACT_HANDOFF for item in ledger.appointments)
    closed_lost = sum(item.status == ShowingStatus.CLOSED_LOST for item in ledger.appointments)
    eligible_showings = max(1, attended + no_shows)
    return ShowingFunnelSnapshot(
        total=total,
        scheduled=scheduled,
        confirmed=confirmed,
        attended=attended,
        no_shows=no_shows,
        cancelled=cancelled,
        contract_handoffs=contract_handoffs,
        closed_lost=closed_lost,
        confirmation_rate=(confirmed / total if total else 0.0),
        show_rate=(attended / eligible_showings if attended + no_shows else 0.0),
        no_show_rate=(no_shows / eligible_showings if attended + no_shows else 0.0),
        showing_to_contract_rate=(contract_handoffs / attended if attended else 0.0),
    )


def build_property_objections(
    ledger: ShowingConversionLedger,
    properties: Sequence[OwnerFinanceProperty],
) -> list[PropertyObjectionSummary]:
    property_labels = {str(item.property_id): item.display_address for item in properties}
    property_ids = sorted({item.property_id for item in ledger.appointments})
    rows: list[PropertyObjectionSummary] = []
    for property_id in property_ids:
        appointments = [item for item in ledger.appointments if item.property_id == property_id]
        attended = [
            item
            for item in appointments
            if item.attended_at is not None
            or item.status in {ShowingStatus.ATTENDED, ShowingStatus.CONTRACT_HANDOFF, ShowingStatus.CLOSED_LOST}
        ]
        counts = Counter(
            item.objection_category.value
            for item in attended
            if item.objection_category != ObjectionCategory.NONE
        )
        top_objection, top_count = counts.most_common(1)[0] if counts else ("None recorded", 0)
        breakdown = ", ".join(f"{name}: {count}" for name, count in counts.most_common()) or "None recorded"
        contract_handoffs = sum(item.status == ShowingStatus.CONTRACT_HANDOFF for item in appointments)
        rows.append(
            PropertyObjectionSummary(
                property_id=property_id,
                property_address=property_labels.get(property_id, f"Property {property_id[:8]}"),
                attended_showings=len(attended),
                contract_handoffs=contract_handoffs,
                top_objection=top_objection,
                objection_count=top_count,
                objection_breakdown=breakdown,
                conversion_rate=(contract_handoffs / len(attended) if attended else 0.0),
            )
        )
    return sorted(rows, key=lambda item: (-item.attended_showings, -item.objection_count, item.property_address.casefold()))


def queue_rows(items: Sequence[ShowingQueueItem]) -> list[dict[str, str | int]]:
    return [
        {
            "Priority": item.priority.value,
            "Buyer": item.buyer_name,
            "Property": item.property_address,
            "Showing": item.scheduled_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Status": item.status.value,
            "Owner": item.owner,
            "Permitted Contact": ", ".join(item.contact_channels) or "None",
            "Decision": item.decision.value,
            "Objection": item.objection_category.value,
            "Next Action": item.recommended_action,
            "Reason": item.reason,
        }
        for item in items
    ]


def reminder_rows(reminders: Sequence[ShowingReminder]) -> list[dict[str, str]]:
    return [
        {
            "Due": item.scheduled_for.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Type": item.reminder_type.value,
            "Channel": item.channel,
            "Status": item.status.value,
            "Message": item.message,
            "Approved By": item.approved_by or "—",
            "Notes": item.notes or "—",
        }
        for item in sorted(reminders, key=lambda reminder: reminder.scheduled_for)
    ]


def objection_rows(items: Sequence[PropertyObjectionSummary]) -> list[dict[str, str | int]]:
    return [
        {
            "Property": item.property_address,
            "Attended Showings": item.attended_showings,
            "Contract Handoffs": item.contract_handoffs,
            "Showing → Contract": f"{item.conversion_rate:.1%}",
            "Top Objection": item.top_objection,
            "Top Count": item.objection_count,
            "All Objections": item.objection_breakdown,
        }
        for item in items
    ]


def event_rows(
    ledger: ShowingConversionLedger,
    appointments_by_id: Mapping[str, ShowingAppointment] | None = None,
) -> list[dict[str, str]]:
    appointments = appointments_by_id or {item.appointment_id: item for item in ledger.appointments}
    return [
        {
            "When": event.occurred_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Appointment": event.appointment_id[:8],
            "Property ID": appointments.get(event.appointment_id).property_id if appointments.get(event.appointment_id) else "—",
            "Event": event.event_type,
            "From": event.from_status or "—",
            "To": event.to_status or "—",
            "Actor": event.actor or "—",
            "Notes": event.notes or "—",
        }
        for event in sorted(ledger.events, key=lambda item: item.occurred_at, reverse=True)
    ]


class ShowingConversionStore:
    """Private Supabase Storage ledger for showing operations and outcomes."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise ShowingConversionError("Supabase is not configured for showing records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise ShowingConversionError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(SHOWING_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    SHOWING_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": SHOWING_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise ShowingConversionError("Could not create the private showing bucket.") from exc
        self._bucket_ready = True

    def load(self) -> ShowingConversionLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(SHOWING_BUCKET).download(SHOWING_PATH)
        except Exception:
            return ShowingConversionLedger()
        try:
            payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            return ShowingConversionLedger.model_validate_json(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ShowingConversionError("The saved showing ledger could not be read.") from exc

    def save(self, ledger: ShowingConversionLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > SHOWING_MAX_BYTES:
            raise ShowingConversionError("The showing ledger is too large to save.")
        try:
            self._client.storage.from_(SHOWING_BUCKET).upload(
                path=SHOWING_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise ShowingConversionError("Could not save the showing ledger.") from exc
