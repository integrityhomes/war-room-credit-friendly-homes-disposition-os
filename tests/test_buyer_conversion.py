from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfh_disposition.buyer_conversion import (
    ActivityType,
    BuyerConversionError,
    BuyerConversionLedger,
    ConversionPriority,
    ConversionStage,
    build_conversion_queue,
    build_funnel_snapshot,
    build_property_pipeline,
    contact_permissions,
    create_conversion_record,
    record_activity,
    schedule_follow_up,
    transition_record,
)
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty, PropertyStatus

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def buyer(**overrides) -> BuyerProfile:
    values = {
        "first_name": "Jordan",
        "last_name": "Lee",
        "email": "jordan@example.com",
        "phone": "5551234567",
        "email_consent": True,
        "sms_consent": True,
        "call_consent": True,
        "preferred_cities": ["Decatur"],
        "preferred_states": ["IL"],
        "maximum_monthly_payment": Decimal("1200"),
        "available_down_payment": Decimal("3000"),
    }
    values.update(overrides)
    return BuyerProfile(**values)


def property_record(**overrides) -> OwnerFinanceProperty:
    values = {
        "status": PropertyStatus.LIVE,
        "address": "945 W Packard St",
        "city": "Decatur",
        "state": "IL",
        "zip_code": "62522",
        "down_payment": Decimal("2000"),
        "monthly_payment": Decimal("950"),
    }
    values.update(overrides)
    return OwnerFinanceProperty(**values)


def seeded() -> tuple[BuyerConversionLedger, BuyerProfile, OwnerFinanceProperty, str]:
    selected_buyer = buyer()
    selected_property = property_record()
    ledger = create_conversion_record(
        BuyerConversionLedger(),
        selected_buyer,
        selected_property,
        owner="Sabrina",
        source="Dwelyx",
        now=NOW,
    )
    return ledger, selected_buyer, selected_property, ledger.records[0].record_id


def test_create_record_sets_first_action_and_audit_event() -> None:
    ledger, selected_buyer, selected_property, _ = seeded()

    assert len(ledger.records) == 1
    assert ledger.records[0].stage == ConversionStage.NEW_LEAD
    assert ledger.records[0].next_action_at == NOW + timedelta(hours=2)
    assert ledger.events[0].event_type == "Record Created"
    assert ledger.records[0].buyer_id == str(selected_buyer.buyer_id)
    assert ledger.records[0].property_id == str(selected_property.property_id)


def test_duplicate_active_buyer_property_record_is_blocked() -> None:
    ledger, selected_buyer, selected_property, _ = seeded()

    with pytest.raises(BuyerConversionError, match="already exists"):
        create_conversion_record(ledger, selected_buyer, selected_property, now=NOW)


def test_do_not_contact_buyer_cannot_enter_new_follow_up_sequence() -> None:
    with pytest.raises(BuyerConversionError, match="Do Not Contact"):
        create_conversion_record(BuyerConversionLedger(), buyer(do_not_contact=True), property_record(), now=NOW)


def test_sold_property_cannot_receive_new_conversion_record() -> None:
    with pytest.raises(BuyerConversionError, match="sold property"):
        create_conversion_record(
            BuyerConversionLedger(),
            buyer(),
            property_record(status=PropertyStatus.SOLD),
            now=NOW,
        )


def test_contact_permissions_honor_each_saved_consent() -> None:
    channels, block = contact_permissions(
        buyer(email_consent=True, sms_consent=False, call_consent=False)
    )
    dnc_channels, dnc_block = contact_permissions(buyer(do_not_contact=True))

    assert channels == ("Email",)
    assert block == ""
    assert dnc_channels == ()
    assert "Do Not Contact" in dnc_block


def test_transition_records_stage_change_and_creates_next_action() -> None:
    ledger, _, _, record_id = seeded()
    updated = transition_record(
        ledger,
        record_id=record_id,
        new_stage=ConversionStage.QUALIFIED,
        actor="Sabrina",
        notes="Payment and down payment fit confirmed.",
        now=NOW + timedelta(hours=1),
    )

    record = updated.records[0]
    assert record.stage == ConversionStage.QUALIFIED
    assert "Dwelyx application" in record.next_action
    assert record.next_action_at == NOW + timedelta(hours=25)
    assert updated.events[-1].from_stage == ConversionStage.NEW_LEAD.value
    assert updated.events[-1].to_stage == ConversionStage.QUALIFIED.value


def test_lost_and_paused_stages_require_reasons() -> None:
    ledger, _, _, record_id = seeded()

    with pytest.raises(BuyerConversionError, match="lost reason"):
        transition_record(
            ledger,
            record_id=record_id,
            new_stage=ConversionStage.LOST,
            actor="Sabrina",
            now=NOW,
        )
    with pytest.raises(BuyerConversionError, match="pause reason"):
        transition_record(
            ledger,
            record_id=record_id,
            new_stage=ConversionStage.PAUSED,
            actor="Sabrina",
            now=NOW,
        )


def test_terminal_record_cannot_be_reopened_accidentally() -> None:
    ledger, _, _, record_id = seeded()
    closed = transition_record(
        ledger,
        record_id=record_id,
        new_stage=ConversionStage.FILLED,
        actor="Sabrina",
        now=NOW + timedelta(days=1),
    )

    assert closed.records[0].next_action == ""
    assert closed.records[0].next_action_at is None
    with pytest.raises(BuyerConversionError, match="closed"):
        transition_record(
            closed,
            record_id=record_id,
            new_stage=ConversionStage.CONTACTED,
            actor="Sabrina",
            now=NOW + timedelta(days=2),
        )


def test_activity_updates_contact_time_and_attempt_count() -> None:
    ledger, _, _, record_id = seeded()
    updated = record_activity(
        ledger,
        record_id=record_id,
        activity_type=ActivityType.CONTACT_ATTEMPT,
        actor="Carlos",
        notes="Left voicemail.",
        now=NOW + timedelta(hours=3),
    )

    assert updated.records[0].contact_attempts == 1
    assert updated.records[0].last_contact_at == NOW + timedelta(hours=3)
    assert updated.events[-1].event_type == ActivityType.CONTACT_ATTEMPT.value


def test_overdue_and_stalled_record_becomes_urgent() -> None:
    ledger, selected_buyer, selected_property, _ = seeded()
    queue = build_conversion_queue(
        ledger,
        [selected_buyer],
        [selected_property],
        now=NOW + timedelta(days=3),
    )

    assert queue[0].priority == ConversionPriority.URGENT
    assert queue[0].overdue_days >= 2
    assert "overdue" in queue[0].reason.lower()


def test_missing_consent_places_record_on_compliance_hold() -> None:
    selected_buyer = buyer(email_consent=False, sms_consent=False, call_consent=False)
    selected_property = property_record()
    ledger = create_conversion_record(
        BuyerConversionLedger(),
        selected_buyer,
        selected_property,
        now=NOW,
    )
    queue = build_conversion_queue(ledger, [selected_buyer], [selected_property], now=NOW)

    assert queue[0].priority == ConversionPriority.COMPLIANCE_HOLD
    assert queue[0].contact_channels == ()
    assert "No saved contact consent" in queue[0].contact_block


def test_sold_property_creates_urgent_reassignment_action() -> None:
    ledger, selected_buyer, selected_property, _ = seeded()
    sold_version = selected_property.model_copy(update={"status": PropertyStatus.SOLD})
    queue = build_conversion_queue(ledger, [selected_buyer], [sold_version], now=NOW)

    assert queue[0].priority == ConversionPriority.URGENT
    assert "reassign" in queue[0].recommended_action.lower()


def test_follow_up_schedule_is_saved_with_audit_event() -> None:
    ledger, _, _, record_id = seeded()
    due = NOW + timedelta(days=2)
    updated = schedule_follow_up(
        ledger,
        record_id=record_id,
        next_action="Call after the buyer uploads documents.",
        next_action_at=due,
        actor="Sabrina",
        now=NOW + timedelta(hours=1),
    )

    assert updated.records[0].next_action_at == due
    assert updated.records[0].next_action.startswith("Call after")
    assert updated.events[-1].event_type == "Follow-Up Scheduled"


def test_funnel_and_property_scoreboards_count_progress() -> None:
    selected_property = property_record()
    first_buyer = buyer(first_name="Jordan")
    second_buyer = buyer(first_name="Morgan", email="morgan@example.com")
    ledger = create_conversion_record(BuyerConversionLedger(), first_buyer, selected_property, now=NOW)
    first_id = ledger.records[0].record_id
    ledger = transition_record(
        ledger,
        record_id=first_id,
        new_stage=ConversionStage.FILLED,
        actor="Sabrina",
        now=NOW + timedelta(days=2),
    )
    ledger = create_conversion_record(ledger, second_buyer, selected_property, now=NOW + timedelta(days=2))
    second_id = ledger.records[-1].record_id
    ledger = transition_record(
        ledger,
        record_id=second_id,
        new_stage=ConversionStage.APPLICATION_SUBMITTED,
        actor="Sabrina",
        now=NOW + timedelta(days=3),
    )

    snapshot = build_funnel_snapshot(
        ledger,
        [first_buyer, second_buyer],
        [selected_property],
        now=NOW + timedelta(days=3),
    )
    property_rows = build_property_pipeline(
        ledger,
        [first_buyer, second_buyer],
        [selected_property],
        now=NOW + timedelta(days=3),
    )

    assert snapshot.total_records == 2
    assert snapshot.applications == 2
    assert snapshot.filled == 1
    assert snapshot.application_rate == 1.0
    assert property_rows[0].active_buyers == 1
    assert property_rows[0].applications == 2
    assert property_rows[0].filled == 1
