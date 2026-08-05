from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from cfh_disposition.buyer_conversion import (
    BuyerConversionLedger,
    ConversionRecord,
    ConversionStage,
)
from cfh_disposition.models import (
    BuyerProfile,
    CommunicationPreference,
    OwnerFinanceProperty,
    PropertyStatus,
)
from cfh_disposition.showing_conversion import (
    ObjectionCategory,
    ReminderStatus,
    ReminderType,
    ShowingConversionError,
    ShowingConversionLedger,
    ShowingConversionStore,
    ShowingDecision,
    ShowingPriority,
    ShowingStatus,
    build_property_objections,
    build_showing_funnel,
    build_showing_queue,
    cancel_appointment,
    confirm_appointment,
    contact_permissions,
    create_appointment,
    find_appointment,
    record_attendance_outcome,
    record_no_show,
    reschedule_appointment,
    sync_conversion_for_confirmation,
    sync_conversion_for_no_show,
    sync_conversion_for_outcome,
    sync_conversion_for_scheduled_showing,
    update_reminder,
)

NOW = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
SHOWING_TIME = NOW + timedelta(days=2)


def buyer(*, consent: bool = True, do_not_contact: bool = False) -> BuyerProfile:
    return BuyerProfile(
        buyer_id=uuid4(),
        first_name="Taylor",
        last_name="Buyer",
        email="taylor@example.com",
        phone="5555551212",
        email_consent=consent,
        sms_consent=consent,
        call_consent=consent,
        do_not_contact=do_not_contact,
        communication_preference=CommunicationPreference.SMS,
    )


def property_record(*, status: PropertyStatus = PropertyStatus.LIVE) -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        property_id=uuid4(),
        status=status,
        address="101 Main St",
        city="Decatur",
        state="IL",
        zip_code="62521",
        occupancy="Vacant",
        down_payment=2500,
        monthly_payment=895,
        showing_instructions="Meet the team member at the front entrance.",
    )


def conversion_record(buyer_record: BuyerProfile, home: OwnerFinanceProperty) -> ConversionRecord:
    return ConversionRecord(
        buyer_id=str(buyer_record.buyer_id),
        property_id=str(home.property_id),
        stage=ConversionStage.APPLICATION_SUBMITTED,
        owner="Sabrina",
        source="Dwelyx",
        next_action="Schedule showing",
        next_action_at=NOW + timedelta(hours=2),
        last_activity_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def ledgers(
    buyer_record: BuyerProfile | None = None,
    home: OwnerFinanceProperty | None = None,
):
    buyer_record = buyer_record or buyer()
    home = home or property_record()
    record = conversion_record(buyer_record, home)
    return (
        buyer_record,
        home,
        BuyerConversionLedger(updated_at=NOW, records=[record]),
        ShowingConversionLedger(updated_at=NOW),
        record,
    )


def scheduled_showing(*, consent: bool = True):
    buyer_record, home, conversion_ledger, showing_ledger, record = ledgers(
        buyer_record=buyer(consent=consent)
    )
    updated, appointment = create_appointment(
        showing_ledger,
        conversion_ledger,
        buyer_record,
        home,
        conversion_record_id=record.record_id,
        scheduled_at=SHOWING_TIME,
        owner="Sabrina",
        buyer_instructions="Meet at the front entrance.",
        now=NOW,
    )
    return buyer_record, home, conversion_ledger, updated, record, appointment


def test_contact_permissions_respect_consent_and_do_not_contact() -> None:
    allowed = buyer(consent=True)
    channels, block = contact_permissions(allowed)
    assert channels == ("SMS", "Email", "Phone")
    assert block == ""

    blocked = buyer(consent=True, do_not_contact=True)
    channels, block = contact_permissions(blocked)
    assert channels == ()
    assert "Do Not Contact" in block


def test_create_appointment_builds_consent_based_reminders() -> None:
    buyer_record, home, conversion_ledger, showing_ledger, record = ledgers()
    updated, appointment = create_appointment(
        showing_ledger,
        conversion_ledger,
        buyer_record,
        home,
        conversion_record_id=record.record_id,
        scheduled_at=SHOWING_TIME,
        owner="Sabrina",
        buyer_instructions="Meet at the front entrance.",
        now=NOW,
    )
    assert appointment.status == ShowingStatus.SCHEDULED
    assert len(updated.appointments) == 1
    assert {item.reminder_type for item in updated.reminders} == {
        ReminderType.CONFIRMATION,
        ReminderType.DAY_BEFORE,
        ReminderType.TWO_HOUR,
    }
    assert all(item.channel == "SMS" for item in updated.reminders)
    assert all("101 Main St" in item.message for item in updated.reminders)


def test_create_appointment_without_consent_creates_no_reminder() -> None:
    buyer_record, home, conversion_ledger, showing_ledger, record = ledgers(
        buyer_record=buyer(consent=False)
    )
    updated, _ = create_appointment(
        showing_ledger,
        conversion_ledger,
        buyer_record,
        home,
        conversion_record_id=record.record_id,
        scheduled_at=SHOWING_TIME,
        owner="Sabrina",
        now=NOW,
    )
    assert updated.reminders == []


def test_duplicate_active_appointment_is_blocked() -> None:
    buyer_record, home, conversion_ledger, showing_ledger, record, _ = scheduled_showing()
    with pytest.raises(ShowingConversionError, match="active showing"):
        create_appointment(
            showing_ledger,
            conversion_ledger,
            buyer_record,
            home,
            conversion_record_id=record.record_id,
            scheduled_at=SHOWING_TIME + timedelta(days=1),
            owner="Sabrina",
            now=NOW,
        )


def test_unavailable_property_cannot_receive_showing() -> None:
    buyer_record = buyer()
    home = property_record(status=PropertyStatus.FILLED)
    record = conversion_record(buyer_record, home)
    conversion_ledger = BuyerConversionLedger(records=[record])
    with pytest.raises(ShowingConversionError, match="not currently available"):
        create_appointment(
            ShowingConversionLedger(),
            conversion_ledger,
            buyer_record,
            home,
            conversion_record_id=record.record_id,
            scheduled_at=SHOWING_TIME,
            owner="Sabrina",
            now=NOW,
        )


def test_confirmation_updates_status_and_follow_up() -> None:
    _, _, _, showing_ledger, _, appointment = scheduled_showing()
    updated = confirm_appointment(
        showing_ledger,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        now=NOW + timedelta(hours=1),
    )
    saved = find_appointment(updated, appointment.appointment_id)
    assert saved.status == ShowingStatus.CONFIRMED
    assert saved.confirmed_at == NOW + timedelta(hours=1)
    assert saved.next_action_at == SHOWING_TIME + timedelta(hours=1)


def test_reschedule_skips_old_reminders_and_builds_new_ones() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    updated = reschedule_appointment(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        new_scheduled_at=SHOWING_TIME + timedelta(days=2),
        actor="Sabrina",
        reason="Buyer requested a later date",
        now=NOW + timedelta(hours=1),
    )
    saved = find_appointment(updated, appointment.appointment_id)
    assert saved.reschedule_count == 1
    assert saved.status == ShowingStatus.SCHEDULED
    skipped = [item for item in updated.reminders if item.status == ReminderStatus.SKIPPED]
    ready = [item for item in updated.reminders if item.status == ReminderStatus.READY]
    assert len(skipped) == 3
    assert len(ready) == 3


def test_no_show_creates_urgent_recovery_reminder() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    updated = record_no_show(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        notes="Buyer did not arrive",
        now=SHOWING_TIME + timedelta(minutes=10),
    )
    saved = find_appointment(updated, appointment.appointment_id)
    assert saved.status == ShowingStatus.NO_SHOW
    assert saved.next_action_at == SHOWING_TIME + timedelta(minutes=25)
    recovery = [
        item
        for item in updated.reminders
        if item.reminder_type == ReminderType.NO_SHOW_RECOVERY
    ]
    assert len(recovery) == 1
    assert recovery[0].status == ReminderStatus.READY


def test_objection_requires_notes() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    with pytest.raises(ShowingConversionError, match="Add notes"):
        record_attendance_outcome(
            showing_ledger,
            buyer_record,
            home,
            appointment_id=appointment.appointment_id,
            actor="Sabrina",
            decision=ShowingDecision.NEEDS_FOLLOW_UP,
            objection_category=ObjectionCategory.DOWN_PAYMENT,
            now=SHOWING_TIME,
        )


def test_not_interested_requires_feedback() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    with pytest.raises(ShowingConversionError, match="why the buyer"):
        record_attendance_outcome(
            showing_ledger,
            buyer_record,
            home,
            appointment_id=appointment.appointment_id,
            actor="Sabrina",
            decision=ShowingDecision.NOT_INTERESTED,
            now=SHOWING_TIME,
        )


def test_ready_for_contract_creates_contract_handoff() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    updated = record_attendance_outcome(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        decision=ShowingDecision.READY_FOR_CONTRACT,
        feedback_summary="Buyer wants to proceed with the saved terms.",
        now=SHOWING_TIME,
    )
    saved = find_appointment(updated, appointment.appointment_id)
    assert saved.status == ShowingStatus.CONTRACT_HANDOFF
    assert saved.contract_handoff_by == "Sabrina"
    assert saved.contract_handoff_at == SHOWING_TIME


def test_attended_follow_up_adds_post_showing_reminder() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    updated = record_attendance_outcome(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        decision=ShowingDecision.NEEDS_FOLLOW_UP,
        objection_category=ObjectionCategory.CONDITION_REPAIRS,
        objection_notes="Buyer wants an estimate for the kitchen work.",
        feedback_summary="Buyer remains interested after repair review.",
        now=SHOWING_TIME,
    )
    saved = find_appointment(updated, appointment.appointment_id)
    assert saved.status == ShowingStatus.ATTENDED
    assert any(
        item.reminder_type == ReminderType.POST_SHOWING
        for item in updated.reminders
    )


def test_cancel_skips_remaining_reminders() -> None:
    _, _, _, showing_ledger, _, appointment = scheduled_showing()
    updated = cancel_appointment(
        showing_ledger,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        reason="Buyer withdrew",
        now=NOW + timedelta(hours=1),
    )
    saved = find_appointment(updated, appointment.appointment_id)
    assert saved.status == ShowingStatus.CANCELLED
    assert all(item.status == ReminderStatus.SKIPPED for item in updated.reminders)


def test_reminder_status_is_audited() -> None:
    _, _, _, showing_ledger, _, appointment = scheduled_showing()
    reminder = showing_ledger.reminders[0]
    updated = update_reminder(
        showing_ledger,
        reminder_id=reminder.reminder_id,
        status=ReminderStatus.SENT_MANUALLY,
        actor="Sabrina",
        notes="Sent through the consented SMS system",
        now=NOW + timedelta(minutes=5),
    )
    saved = next(item for item in updated.reminders if item.reminder_id == reminder.reminder_id)
    assert saved.status == ReminderStatus.SENT_MANUALLY
    assert saved.sent_at == NOW + timedelta(minutes=5)
    assert updated.events[-1].event_type == "Reminder Sent Manually"


def test_queue_prioritizes_unconfirmed_showing_inside_two_hours() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    queue = build_showing_queue(
        showing_ledger,
        [buyer_record],
        [home],
        now=SHOWING_TIME - timedelta(minutes=90),
    )
    assert queue[0].appointment_id == appointment.appointment_id
    assert queue[0].priority == ShowingPriority.URGENT
    assert "Confirm" in queue[0].recommended_action


def test_queue_prioritizes_no_show_recovery() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    updated = record_no_show(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        now=SHOWING_TIME,
    )
    queue = build_showing_queue(updated, [buyer_record], [home], now=SHOWING_TIME)
    assert queue[0].priority == ShowingPriority.URGENT
    assert "another available time" in queue[0].recommended_action


def test_showing_funnel_math() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    attended = record_attendance_outcome(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        decision=ShowingDecision.READY_FOR_CONTRACT,
        feedback_summary="Proceed",
        now=SHOWING_TIME,
    )
    funnel = build_showing_funnel(attended)
    assert funnel.total == 1
    assert funnel.attended == 1
    assert funnel.contract_handoffs == 1
    assert funnel.show_rate == 1.0
    assert funnel.showing_to_contract_rate == 1.0


def test_property_objection_summary_counts_patterns() -> None:
    buyer_record, home, _, showing_ledger, _, appointment = scheduled_showing()
    updated = record_attendance_outcome(
        showing_ledger,
        buyer_record,
        home,
        appointment_id=appointment.appointment_id,
        actor="Sabrina",
        decision=ShowingDecision.NEEDS_FOLLOW_UP,
        objection_category=ObjectionCategory.MONTHLY_PAYMENT,
        objection_notes="Buyer needs a lower monthly payment.",
        feedback_summary="Interested if terms change.",
        now=SHOWING_TIME,
    )
    rows = build_property_objections(updated, [home])
    assert len(rows) == 1
    assert rows[0].top_objection == ObjectionCategory.MONTHLY_PAYMENT.value
    assert rows[0].objection_count == 1


def test_scheduling_sync_moves_conversion_to_showing_scheduled() -> None:
    _, _, conversion_ledger, showing_ledger, _, appointment = scheduled_showing()
    updated = sync_conversion_for_scheduled_showing(
        conversion_ledger,
        appointment,
        actor="Sabrina",
        now=NOW,
    )
    assert updated.records[0].stage == ConversionStage.SHOWING_SCHEDULED
    assert updated.events[-1].event_type == "Stage Changed"


def test_confirmation_sync_records_showing_confirmed_activity() -> None:
    _, _, conversion_ledger, showing_ledger, _, appointment = scheduled_showing()
    scheduled = sync_conversion_for_scheduled_showing(
        conversion_ledger,
        appointment,
        actor="Sabrina",
        now=NOW,
    )
    updated = sync_conversion_for_confirmation(
        scheduled,
        appointment,
        actor="Sabrina",
        now=NOW + timedelta(hours=1),
    )
    assert updated.events[-1].event_type == "Showing Confirmed"


def test_no_show_sync_creates_fast_follow_up() -> None:
    _, _, conversion_ledger, showing_ledger, _, appointment = scheduled_showing()
    scheduled = sync_conversion_for_scheduled_showing(
        conversion_ledger,
        appointment,
        actor="Sabrina",
        now=NOW,
    )
    updated = sync_conversion_for_no_show(
        scheduled,
        appointment,
        actor="Sabrina",
        now=SHOWING_TIME,
    )
    assert updated.records[0].next_action_at == SHOWING_TIME + timedelta(minutes=15)
    assert updated.events[-1].event_type == "Follow-Up Scheduled"


def test_outcome_sync_can_move_buyer_to_contract_pending() -> None:
    _, _, conversion_ledger, _, _, appointment = scheduled_showing()
    scheduled = sync_conversion_for_scheduled_showing(
        conversion_ledger,
        appointment,
        actor="Sabrina",
        now=NOW,
    )
    appointment = appointment.model_copy(
        update={
            "status": ShowingStatus.CONTRACT_HANDOFF,
            "decision": ShowingDecision.READY_FOR_CONTRACT,
            "feedback_summary": "Buyer is ready to sign.",
        }
    )
    updated = sync_conversion_for_outcome(
        scheduled,
        appointment,
        actor="Sabrina",
        target_stage=ConversionStage.CONTRACT_PENDING,
        now=SHOWING_TIME,
    )
    assert updated.records[0].stage == ConversionStage.CONTRACT_PENDING


def test_lost_outcome_requires_reason() -> None:
    _, _, conversion_ledger, _, _, appointment = scheduled_showing()
    scheduled = sync_conversion_for_scheduled_showing(
        conversion_ledger,
        appointment,
        actor="Sabrina",
        now=NOW,
    )
    with pytest.raises(ShowingConversionError, match="lost reason"):
        sync_conversion_for_outcome(
            scheduled,
            appointment,
            actor="Sabrina",
            target_stage=ConversionStage.LOST,
            now=SHOWING_TIME,
        )


class FakeBucket:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def download(self, path: str) -> bytes:
        if path not in self.files:
            raise RuntimeError("missing")
        return self.files[path]

    def upload(self, *, path: str, file: bytes, file_options: dict[str, str]) -> None:
        self.files[path] = file


class FakeStorage:
    def __init__(self) -> None:
        self.bucket = FakeBucket()
        self.created = False

    def get_bucket(self, name: str):
        if not self.created:
            raise RuntimeError("missing")
        return {"name": name}

    def create_bucket(self, name: str, options: dict[str, object]):
        self.created = True
        return {"name": name}

    def from_(self, name: str) -> FakeBucket:
        return self.bucket


class FakeClient:
    def __init__(self) -> None:
        self.storage = FakeStorage()


def test_private_showing_store_round_trip() -> None:
    client = FakeClient()
    store = ShowingConversionStore(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "secret",
        },
        client=client,
    )
    _, _, _, ledger, _, _ = scheduled_showing()
    store.save(ledger)
    loaded = store.load()
    assert len(loaded.appointments) == 1
    assert len(loaded.reminders) == 3
