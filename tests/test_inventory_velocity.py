from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.campaign_launch import (
    LaunchStatus,
    new_launch_state,
    set_channel_status,
)
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionEvent,
    DwelyxEventType,
)
from cfh_disposition.inventory_velocity import (
    EscalationLevel,
    EscalationTaskStatus,
    FunnelBottleneck,
    InterventionType,
    InventoryVelocityError,
    InventoryVelocityLedger,
    PropertyVelocityProfile,
    add_escalation_task,
    assess_property,
    build_property_signals,
    build_velocity_queue,
    suggested_task,
    update_escalation_task,
    upsert_profile,
)
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus

NOW = datetime(2026, 8, 5, 18, 0, tzinfo=UTC)


def property_record(**overrides) -> OwnerFinanceProperty:
    values = {
        "status": PropertyStatus.LIVE,
        "address": "945 W Packard St",
        "city": "Decatur",
        "state": "IL",
        "zip_code": "62522",
        "occupancy": "Vacant",
        "created_at": NOW - timedelta(days=30),
        "updated_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return OwnerFinanceProperty(**values)


def active_launch(item: OwnerFinanceProperty, count: int = 15):
    state = new_launch_state(item.property_id, "owner_finance_homes", now=NOW - timedelta(days=10))
    keys = list(state.channels)[:count]
    for key in keys:
        state = set_channel_status(
            state,
            key,
            LaunchStatus.POSTED,
            updated_by="Sabrina",
            now=NOW - timedelta(days=10),
        )
    return state


def click(item: OwnerFinanceProperty, days_ago: int = 1) -> ClickEvent:
    return ClickEvent(
        occurred_at=NOW - timedelta(days=days_ago),
        source="credit_friendly_homes",
        medium="nextdoor",
        campaign="owner_finance_homes",
        property_id=str(item.property_id),
    )


def result_event(
    item: OwnerFinanceProperty,
    buyer_id: str,
    event_type: DwelyxEventType,
    *,
    days_ago: int = 1,
) -> DwelyxAttributionEvent:
    return DwelyxAttributionEvent(
        event_id=f"event-{buyer_id}-{event_type.value.replace('.', '-')}",
        event_type=event_type,
        occurred_at=NOW - timedelta(days=days_ago),
        dwelyx_buyer_id=buyer_id,
        cfh_property_id=str(item.property_id),
        medium="nextdoor",
        campaign="owner_finance_homes",
    )


def test_saved_start_date_and_holding_cost_are_used() -> None:
    item = property_record()
    profile = PropertyVelocityProfile(
        property_id=str(item.property_id),
        marketing_started_at=NOW - timedelta(days=12),
        target_fill_days=10,
        daily_holding_cost=Decimal("25"),
    )
    ledger = upsert_profile(InventoryVelocityLedger(), profile, now=NOW)

    signals = build_property_signals(
        item,
        ledger=ledger,
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )

    assert signals.days_marketed == 12
    assert signals.marketing_age_source == "Saved marketing start date"
    assert signals.target_fill_days == 10
    assert signals.estimated_holding_cost == Decimal("300")


def test_zero_active_channels_creates_marketing_not_live_escalation() -> None:
    item = property_record()
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        launch_state=None,
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert assessment.bottleneck == FunnelBottleneck.NOT_LIVE
    assert assessment.primary_intervention == InterventionType.ACTIVATE_CHANNELS
    assert assessment.level in {EscalationLevel.HIGH, EscalationLevel.CRITICAL}


def test_active_channels_with_no_clicks_identifies_traffic_problem() -> None:
    item = property_record(created_at=NOW - timedelta(days=5))
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert assessment.bottleneck == FunnelBottleneck.NO_TRAFFIC
    assert assessment.primary_intervention == InterventionType.REFRESH_CREATIVE
    assert assessment.signals.clicks_30 == 0


def test_clicks_before_dwelyx_connection_identify_data_gap() -> None:
    item = property_record(created_at=NOW - timedelta(days=7))
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        click_events=[click(item) for _ in range(12)],
        launch_state=active_launch(item),
        attribution_connected=False,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert assessment.bottleneck == FunnelBottleneck.DATA_GAP
    assert assessment.primary_intervention == InterventionType.CONNECT_DWELYX


def test_clicks_without_registration_identify_page_or_offer_problem() -> None:
    item = property_record(created_at=NOW - timedelta(days=7))
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        click_events=[click(item) for _ in range(12)],
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert assessment.bottleneck == FunnelBottleneck.CLICK_NO_REGISTRATION
    assert assessment.primary_intervention == InterventionType.FIX_LANDING_PAGE


def test_registrations_without_applications_require_management_review() -> None:
    item = property_record(created_at=NOW - timedelta(days=10))
    events = [
        result_event(item, f"buyer-{index}", DwelyxEventType.BUYER_REGISTERED)
        for index in range(3)
    ]
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        click_events=[click(item) for _ in range(15)],
        attribution_events=events,
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert signals.registrations == 3
    assert assessment.bottleneck == FunnelBottleneck.REGISTRATION_NO_APPLICATION
    assert assessment.primary_intervention == InterventionType.REVIEW_TERMS
    assert assessment.manager_approval_required


def test_applications_without_showings_identify_showing_process() -> None:
    item = property_record(created_at=NOW - timedelta(days=10))
    events = [
        result_event(item, f"buyer-{index}", DwelyxEventType.APPLICATION_SUBMITTED)
        for index in range(2)
    ]
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        click_events=[click(item) for _ in range(15)],
        attribution_events=events,
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert signals.applications == 2
    assert signals.showings == 0
    assert assessment.bottleneck == FunnelBottleneck.APPLICATION_NO_SHOWING
    assert assessment.primary_intervention == InterventionType.FIX_SHOWING_PROCESS


def test_showings_without_contract_trigger_price_condition_terms_review() -> None:
    item = property_record(created_at=NOW - timedelta(days=15))
    events = [
        result_event(item, f"buyer-{index}", DwelyxEventType.SHOWING_SCHEDULED)
        for index in range(2)
    ]
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        click_events=[click(item) for _ in range(20)],
        attribution_events=events,
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert signals.showings == 2
    assert assessment.bottleneck == FunnelBottleneck.SHOWING_NO_CONTRACT
    assert assessment.primary_intervention == InterventionType.MANAGER_PRICE_CONDITION_REVIEW
    assert assessment.manager_approval_required
    assert "does not authorize" in suggested_task(assessment, now=NOW).recommended_change.casefold()


def test_contract_result_moves_to_contract_protection_action() -> None:
    item = property_record(created_at=NOW - timedelta(days=8))
    events = [
        result_event(item, "buyer-contract", DwelyxEventType.CONTRACT_SIGNED),
    ]
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        attribution_events=events,
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert signals.contracts == 1
    assert assessment.bottleneck == FunnelBottleneck.CONTRACT_IN_PROGRESS
    assert "signatures" in assessment.primary_action.casefold()


def test_occupied_or_inactive_property_is_not_escalated() -> None:
    item = property_record(occupancy="Occupied")
    signals = build_property_signals(
        item,
        ledger=InventoryVelocityLedger(),
        launch_state=active_launch(item),
        attribution_connected=True,
        now=NOW,
    )
    assessment = assess_property(signals)

    assert assessment.level == EscalationLevel.CLOSED
    assert assessment.bottleneck == FunnelBottleneck.INACTIVE


def test_duplicate_open_task_is_blocked_and_completed_task_can_be_replaced() -> None:
    item = property_record(created_at=NOW - timedelta(days=5))
    assessment = assess_property(
        build_property_signals(
            item,
            ledger=InventoryVelocityLedger(),
            launch_state=active_launch(item),
            attribution_connected=True,
            now=NOW,
        )
    )
    task = suggested_task(assessment, owner="Carlos", now=NOW)
    ledger = add_escalation_task(InventoryVelocityLedger(), task, now=NOW)

    with pytest.raises(InventoryVelocityError, match="already exists"):
        add_escalation_task(ledger, suggested_task(assessment, now=NOW), now=NOW)

    ledger = update_escalation_task(
        ledger,
        task_id=task.task_id,
        status=EscalationTaskStatus.COMPLETED,
        owner="Carlos",
        notes="Creative refreshed.",
        now=NOW + timedelta(hours=2),
    )
    assert ledger.tasks[0].completed_at == NOW + timedelta(hours=2)

    replacement = suggested_task(assessment, now=NOW + timedelta(days=1))
    ledger = add_escalation_task(
        ledger,
        replacement,
        now=NOW + timedelta(days=1),
    )
    assert len(ledger.tasks) == 2


def test_queue_places_critical_property_before_normal_property() -> None:
    critical = property_record(address="100 Critical St", created_at=NOW - timedelta(days=60))
    normal = property_record(address="200 Normal St", created_at=NOW - timedelta(days=2))
    normal_events = [
        result_event(normal, "buyer-normal", DwelyxEventType.BUYER_REGISTERED),
    ]
    launches = {
        str(critical.property_id): None,
        str(normal.property_id): active_launch(normal),
    }
    queue = build_velocity_queue(
        [normal, critical],
        ledger=InventoryVelocityLedger(),
        click_events=[click(normal)],
        attribution_events=normal_events,
        launch_states=launches,
        attribution_connected=True,
        now=NOW,
    )

    assert queue[0].signals.address.startswith("100 Critical")
    assert queue[0].level == EscalationLevel.CRITICAL
