from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from cfh_disposition.buyer_conversion import (
    BuyerConversionLedger,
    ConversionPriority,
    ConversionQueueItem,
    ConversionRecord,
    ConversionStage,
)
from cfh_disposition.executive_command import (
    ExecutiveActionItem,
    ExecutiveLane,
    ExecutivePriority,
    build_executive_snapshot,
    conversion_action_items,
    daily_brief_text,
    deduplicate_and_sort,
    inventory_action_items,
    portfolio_rows,
    property_control_action_items,
    showing_action_items,
    system_action_items,
    terms_action_items,
)
from cfh_disposition.inventory_velocity import (
    InventoryVelocityLedger,
    PropertyVelocityProfile,
    build_velocity_queue,
)
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.property_shutdown import (
    MarketingControlAction,
    PropertyControlLedger,
    append_control_event,
    build_property_control_event,
)
from cfh_disposition.showing_conversion import (
    ObjectionCategory,
    ShowingAppointment,
    ShowingConversionLedger,
    ShowingDecision,
    ShowingPriority,
    ShowingQueueItem,
    ShowingStatus,
)
from cfh_disposition.terms_testing import (
    PhaseMetrics,
    TermsExperimentStatus,
    TermsRecommendation,
    TermsRecommendationResult,
    TermsTestingLedger,
    TermsField,
    apply_challenger,
    approve_experiment,
    build_terms_experiment,
)

NOW = datetime(2026, 8, 5, 17, 0, tzinfo=UTC)


def property_record(*, days_old: int = 30) -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        status=PropertyStatus.LIVE,
        address="100 Main St",
        city="Decatur",
        state="IL",
        zip_code="62521",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("75000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("950"),
        interest_rate=Decimal("10"),
        term_months=360,
        condition_summary="Needs cosmetic work.",
        repairs_needed="Paint and flooring.",
        showing_instructions="Schedule with the team.",
        public_disclosures="Verify all information.",
        occupancy="Vacant",
        created_at=NOW - timedelta(days=days_old),
        updated_at=NOW - timedelta(days=days_old),
    )


def test_deduplicate_and_sort_keeps_highest_priority_copy() -> None:
    normal = ExecutiveActionItem(
        action_id="same",
        priority=ExecutivePriority.NORMAL,
        lane=ExecutiveLane.TEAM,
        source="Test",
        title="Normal",
        action="Act",
        reason="Reason",
    )
    urgent = ExecutiveActionItem(
        action_id="same",
        priority=ExecutivePriority.URGENT,
        lane=ExecutiveLane.TEAM,
        source="Test",
        title="Urgent",
        action="Act now",
        reason="Reason",
    )
    blocked = ExecutiveActionItem(
        action_id="blocked",
        priority=ExecutivePriority.BLOCKED,
        lane=ExecutiveLane.SYSTEM,
        source="Test",
        title="Blocked",
        action="Repair",
        reason="Reason",
    )

    rows = deduplicate_and_sort([normal, urgent, blocked])

    assert [row.action_id for row in rows] == ["blocked", "same"]
    assert rows[1].title == "Urgent"


def test_inventory_critical_assessment_becomes_management_item_when_required() -> None:
    property_item = property_record()
    ledger = InventoryVelocityLedger(
        profiles=[
            PropertyVelocityProfile(
                property_id=str(property_item.property_id),
                marketing_started_at=NOW - timedelta(days=45),
                target_fill_days=14,
                daily_holding_cost=Decimal("25"),
            )
        ]
    )
    assessments = build_velocity_queue(
        [property_item],
        ledger=ledger,
        attribution_connected=True,
        now=NOW,
    )

    items = inventory_action_items(assessments, ledger, now=NOW)

    assert items
    assert items[0].priority == ExecutivePriority.CRITICAL
    assert items[0].property_id == str(property_item.property_id)


def test_conversion_compliance_hold_and_contract_pending_are_included() -> None:
    compliance = ConversionQueueItem(
        record_id="record-hold",
        priority=ConversionPriority.COMPLIANCE_HOLD,
        stage=ConversionStage.APPLICATION_SUBMITTED,
        buyer_name="Buyer Hold",
        property_address="100 Main St",
        property_status="Marketing Live",
        owner="Carlos",
        days_idle=0,
        overdue_days=0,
        next_action="Do not contact",
        next_action_at=NOW,
        recommended_action="Review consent",
        reason="No saved consent",
        contact_channels=(),
        contact_block="No saved consent",
        contact_attempts=0,
    )
    contract = ConversionQueueItem(
        record_id="record-contract",
        priority=ConversionPriority.NORMAL,
        stage=ConversionStage.CONTRACT_PENDING,
        buyer_name="Buyer Contract",
        property_address="100 Main St",
        property_status="Pending",
        owner="Sabrina",
        days_idle=0,
        overdue_days=0,
        next_action="Finish signatures",
        next_action_at=NOW + timedelta(hours=2),
        recommended_action="Finish signatures",
        reason="Contract is pending",
        contact_channels=("Email",),
        contact_block="",
        contact_attempts=1,
    )

    items = conversion_action_items([contract, compliance], now=NOW)

    assert {item.action_id for item in items} == {"conversion:record-hold", "conversion:record-contract"}
    hold = next(item for item in items if item.action_id.endswith("record-hold"))
    pending = next(item for item in items if item.action_id.endswith("record-contract"))
    assert hold.priority == ExecutivePriority.BLOCKED
    assert hold.lane == ExecutiveLane.COMPLIANCE
    assert pending.priority == ExecutivePriority.URGENT


def test_showing_contract_handoff_is_urgent_even_when_queue_priority_is_normal() -> None:
    queue_item = ShowingQueueItem(
        appointment_id="appointment-1",
        priority=ShowingPriority.NORMAL,
        status=ShowingStatus.CONTRACT_HANDOFF,
        buyer_name="Ready Buyer",
        property_address="100 Main St",
        owner="Sabrina",
        scheduled_at=NOW - timedelta(hours=1),
        minutes_until_showing=-60,
        next_action="Prepare contract",
        next_action_at=NOW,
        recommended_action="Prepare contract",
        reason="Buyer is ready",
        contact_channels=("Phone",),
        contact_block="",
        decision=ShowingDecision.READY_FOR_CONTRACT,
        objection_category=ObjectionCategory.NONE,
    )

    items = showing_action_items([queue_item], now=NOW)

    assert len(items) == 1
    assert items[0].priority == ExecutivePriority.URGENT


def test_terms_draft_is_management_decision_and_applied_test_has_relaunch_item() -> None:
    property_item = property_record(days_old=5)
    experiment = build_terms_experiment(
        property_item,
        "https://dwelyx.com",
        tested_field=TermsField.DOWN_PAYMENT,
        challenger_value=Decimal("4000"),
        baseline_start=date(2026, 7, 15),
        baseline_end=date(2026, 7, 31),
        now=NOW,
    )
    draft_ledger = TermsTestingLedger(experiments=[experiment])

    draft_items = terms_action_items(draft_ledger, now=NOW)

    assert draft_items[0].lane == ExecutiveLane.MANAGEMENT
    assert draft_items[0].manager_only is True

    approved = approve_experiment(
        draft_ledger,
        experiment_id=experiment.experiment_id,
        approved_by="Sabrina",
        approval_reason="Test a lower down payment.",
        now=NOW,
    )
    active_ledger, _ = apply_challenger(
        approved,
        property_item,
        experiment_id=experiment.experiment_id,
        applied_by="Sabrina",
        now=NOW,
    )

    active_items = terms_action_items(active_ledger, now=NOW)

    assert any(item.action_id.startswith("terms-relaunch:") for item in active_items)


def test_terms_protect_contract_is_critical() -> None:
    property_item = property_record(days_old=5)
    experiment = build_terms_experiment(
        property_item,
        "https://dwelyx.com",
        tested_field=TermsField.MONTHLY_PAYMENT,
        challenger_value=Decimal("900"),
        baseline_start=date(2026, 7, 15),
        baseline_end=date(2026, 7, 31),
        now=NOW,
    ).model_copy(update={"status": TermsExperimentStatus.ACTIVE, "applied_at": NOW - timedelta(days=10)})
    empty_metrics = PhaseMetrics(
        phase="Control",
        days=10,
        impressions=0,
        tracked_clicks=0,
        reported_clicks=0,
        usable_clicks=0,
        inquiries=0,
        registrations=0,
        applications=0,
        showings=0,
        contracts=0,
        filled=0,
        spend=Decimal("0"),
        primary_total=0,
        primary_rate=0.0,
        cost_per_application=None,
    )
    result = TermsRecommendationResult(
        recommendation=TermsRecommendation.PROTECT_CONTRACT,
        sample_ready=True,
        lift_percent=0.0,
        control=empty_metrics,
        challenger=empty_metrics,
        reason="A signed contract exists.",
        confidence="High",
    )

    items = terms_action_items(
        TermsTestingLedger(experiments=[experiment]),
        {experiment.experiment_id: result},
        now=NOW,
    )

    decision = next(item for item in items if item.action_id.startswith("terms-decision:"))
    assert decision.priority == ExecutivePriority.CRITICAL


def test_property_control_uses_latest_event_per_property() -> None:
    property_item = property_record(days_old=5)
    paused_property, pause_event = build_property_control_event(
        property_item,
        MarketingControlAction.PAUSE,
        reason="Temporary access issue.",
        requested_by="Sabrina",
        now=NOW - timedelta(days=2),
    )
    _, sold_event = build_property_control_event(
        paused_property,
        MarketingControlAction.SOLD,
        reason="Property sold.",
        requested_by="Sabrina",
        now=NOW - timedelta(hours=2),
    )
    ledger = append_control_event(append_control_event(PropertyControlLedger(), pause_event), sold_event)

    items = property_control_action_items(ledger, now=NOW)

    assert len(items) == 1
    assert "Sold" in items[0].title
    assert items[0].entity_id == sold_event.event_id


def test_snapshot_and_daily_brief_include_portfolio_totals() -> None:
    property_item = property_record()
    velocity_ledger = InventoryVelocityLedger(
        profiles=[
            PropertyVelocityProfile(
                property_id=str(property_item.property_id),
                marketing_started_at=NOW - timedelta(days=30),
                target_fill_days=14,
                daily_holding_cost=Decimal("20"),
            )
        ]
    )
    assessments = build_velocity_queue(
        [property_item],
        ledger=velocity_ledger,
        now=NOW,
    )
    conversion_ledger = BuyerConversionLedger(
        records=[
            ConversionRecord(
                buyer_id=str(uuid4()),
                property_id=str(property_item.property_id),
                stage=ConversionStage.CONTRACT_PENDING,
            )
        ]
    )
    showing_ledger = ShowingConversionLedger(
        appointments=[
            ShowingAppointment(
                conversion_record_id="record-1",
                buyer_id=str(uuid4()),
                property_id=str(property_item.property_id),
                scheduled_at=NOW,
                status=ShowingStatus.CONTRACT_HANDOFF,
            )
        ]
    )
    items = [
        ExecutiveActionItem(
            action_id="critical-1",
            priority=ExecutivePriority.CRITICAL,
            lane=ExecutiveLane.MANAGEMENT,
            source="Test",
            title="Critical decision",
            action="Decide now",
            reason="Risk",
            manager_only=True,
            property_id=str(property_item.property_id),
            property_address=property_item.display_address,
        )
    ]

    snapshot = build_executive_snapshot(
        items,
        [property_item],
        assessments,
        conversion_ledger,
        showing_ledger,
    )
    brief = daily_brief_text(snapshot, items, generated_at=NOW)
    portfolio = portfolio_rows([property_item], assessments, items)

    assert snapshot.active_vacant_properties == 1
    assert snapshot.contract_pending_records == 1
    assert snapshot.showing_contract_handoffs == 1
    assert snapshot.estimated_holding_exposure == Decimal("600")
    assert "Critical decision" in brief
    assert portfolio[0]["Open Actions"] == 1


def test_system_errors_become_blocked_management_items() -> None:
    items = system_action_items({"Dwelyx Results": "Receiver is not connected."}, now=NOW)

    assert len(items) == 1
    assert items[0].priority == ExecutivePriority.BLOCKED
    assert items[0].lane == ExecutiveLane.SYSTEM
    assert items[0].manager_only is True
