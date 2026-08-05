from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionEvent,
    DwelyxEventType,
)
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.terms_testing import (
    RelaunchTaskStatus,
    TermsExperimentStatus,
    TermsField,
    TermsRecommendation,
    TermsTestingError,
    TermsTestingLedger,
    TestPhase,
    apply_challenger,
    approve_decision,
    approve_experiment,
    build_terms_experiment,
    create_experiment,
    find_experiment,
    mark_review_ready,
    phase_metrics,
    recommendation_for_experiment,
    rollback_to_control,
    update_relaunch_task,
    upsert_outcome,
)

NOW = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
BASELINE_START = date(2026, 7, 15)
BASELINE_END = date(2026, 7, 28)


def property_record(**overrides) -> OwnerFinanceProperty:
    values = {
        "status": PropertyStatus.LIVE,
        "address": "945 W Packard St",
        "city": "Decatur",
        "state": "IL",
        "zip_code": "62522",
        "total_price": Decimal("94500"),
        "down_payment": Decimal("2500"),
        "monthly_payment": Decimal("950"),
        "interest_rate": Decimal("10"),
        "term_months": 360,
        "occupancy": "Vacant",
    }
    values.update(overrides)
    return OwnerFinanceProperty(**values)


def draft_experiment(
    item: OwnerFinanceProperty,
    *,
    field: TermsField = TermsField.DOWN_PAYMENT,
    challenger=Decimal("1500"),
    minimum_test_days: int = 7,
    minimum_clicks: int = 10,
    minimum_registrations: int = 3,
    primary_metric: str = "Applications",
):
    return build_terms_experiment(
        item,
        "https://dwelyx.com/homes",
        tested_field=field,
        challenger_value=challenger,
        baseline_start=BASELINE_START,
        baseline_end=BASELINE_END,
        primary_metric=primary_metric,
        minimum_test_days=minimum_test_days,
        minimum_clicks=minimum_clicks,
        minimum_registrations=minimum_registrations,
        now=NOW,
    )


def approve_and_apply(item: OwnerFinanceProperty, experiment, *, applied_at=NOW):
    ledger = create_experiment(TermsTestingLedger(), experiment, now=NOW)
    ledger = approve_experiment(
        ledger,
        experiment_id=experiment.experiment_id,
        approved_by="Sabrina",
        approval_reason="Test a lower down payment to improve application conversion.",
        now=NOW,
    )
    return apply_challenger(
        ledger,
        item,
        experiment_id=experiment.experiment_id,
        applied_by="Sabrina",
        now=applied_at,
    )


def attribution_event(
    experiment,
    event_type: DwelyxEventType,
    *,
    buyer_id: str,
    occurred_at: datetime,
    campaign: str | None = None,
):
    return DwelyxAttributionEvent(
        event_id=f"evt-{buyer_id}-{event_type.value.replace('.', '-')}-{int(occurred_at.timestamp())}",
        event_type=event_type,
        occurred_at=occurred_at,
        dwelyx_buyer_id=buyer_id,
        cfh_property_id=experiment.property_id,
        source="credit_friendly_homes",
        medium="facebook_groups",
        campaign=campaign or experiment.campaign,
    )


def test_build_experiment_changes_one_field_and_covers_all_channels() -> None:
    item = property_record()
    experiment = draft_experiment(item)

    assert experiment.control_terms.down_payment == Decimal("2500")
    assert experiment.challenger_terms.down_payment == Decimal("1500")
    assert experiment.control_terms.monthly_payment == experiment.challenger_terms.monthly_payment
    assert len(experiment.relaunch_tasks) == 15
    assert experiment.relaunch_tasks[0].status == RelaunchTaskStatus.CONFIRMED
    assert experiment.campaign in experiment.tracked_link
    assert str(item.property_id) in experiment.tracked_link


def test_build_rejects_same_value_and_invalid_down_payment() -> None:
    item = property_record()
    with pytest.raises(TermsTestingError, match="different"):
        draft_experiment(item, challenger=Decimal("2500"))
    with pytest.raises(TermsTestingError, match="lower than total price"):
        draft_experiment(item, challenger=Decimal("100000"))


def test_build_rejects_inactive_property() -> None:
    item = property_record(status=PropertyStatus.SOLD)
    with pytest.raises(TermsTestingError, match="launch-ready, live, or paused"):
        draft_experiment(item)


def test_duplicate_active_test_is_blocked() -> None:
    item = property_record()
    first = draft_experiment(item)
    ledger = create_experiment(TermsTestingLedger(), first, now=NOW)
    second = draft_experiment(item)
    with pytest.raises(TermsTestingError, match="active test"):
        create_experiment(ledger, second, now=NOW)


def test_approval_does_not_change_property_and_apply_is_explicit() -> None:
    item = property_record()
    experiment = draft_experiment(item)
    ledger = create_experiment(TermsTestingLedger(), experiment, now=NOW)
    ledger = approve_experiment(
        ledger,
        experiment_id=experiment.experiment_id,
        approved_by="Sabrina",
        approval_reason="Approved controlled test.",
        now=NOW,
    )

    assert item.down_payment == Decimal("2500")
    approved = find_experiment(ledger, experiment.experiment_id)
    assert approved is not None
    assert approved.status == TermsExperimentStatus.APPROVED

    ledger, updated = apply_challenger(
        ledger,
        item,
        experiment_id=experiment.experiment_id,
        applied_by="Sabrina",
        now=NOW,
    )
    active = find_experiment(ledger, experiment.experiment_id)
    assert active is not None
    assert active.status == TermsExperimentStatus.ACTIVE
    assert updated.down_payment == Decimal("1500")
    assert updated.monthly_payment == Decimal("950")
    assert item.down_payment == Decimal("2500")


def test_apply_blocks_stale_property_record() -> None:
    item = property_record()
    experiment = draft_experiment(item)
    ledger = create_experiment(TermsTestingLedger(), experiment, now=NOW)
    ledger = approve_experiment(
        ledger,
        experiment_id=experiment.experiment_id,
        approved_by="Sabrina",
        approval_reason="Approved controlled test.",
        now=NOW,
    )
    changed_item = item.model_copy(update={"monthly_payment": Decimal("1000")})

    with pytest.raises(TermsTestingError, match="changed after this test"):
        apply_challenger(
            ledger,
            changed_item,
            experiment_id=experiment.experiment_id,
            applied_by="Sabrina",
            now=NOW,
        )


def test_relaunch_task_can_be_confirmed() -> None:
    item = property_record()
    experiment = draft_experiment(item)
    ledger, _ = approve_and_apply(item, experiment)
    ledger = update_relaunch_task(
        ledger,
        experiment_id=experiment.experiment_id,
        channel_key="nextdoor",
        status=RelaunchTaskStatus.CONFIRMED,
        updated_by="Sabrina",
        notes="Business Post updated and paid housing ad updated.",
        now=NOW,
    )
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    nextdoor = next(task for task in saved.relaunch_tasks if task.channel_key == "nextdoor")
    assert nextdoor.status == RelaunchTaskStatus.CONFIRMED
    assert "paid housing ad" in nextdoor.notes


def test_manual_outcome_upsert_replaces_matching_period() -> None:
    item = property_record()
    experiment = draft_experiment(item)
    ledger, _ = approve_and_apply(item, experiment)
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        phase=TestPhase.CHALLENGER,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 5),
        impressions=100,
        reported_clicks=12,
        registrations=4,
        applications=2,
        now=NOW,
    )
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        phase=TestPhase.CHALLENGER,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 5),
        impressions=120,
        reported_clicks=15,
        registrations=5,
        applications=3,
        now=NOW,
    )
    assert len(ledger.outcomes) == 1
    assert ledger.outcomes[0].applications == 3
    assert ledger.outcomes[0].reported_clicks == 15


def test_phase_metrics_use_unique_challenger_campaign_and_dwelyx_results() -> None:
    item = property_record()
    experiment = draft_experiment(item, minimum_test_days=1, minimum_clicks=1)
    applied_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    ledger, _ = approve_and_apply(item, experiment, applied_at=applied_at)
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    clicks = [
        ClickEvent(
            occurred_at=applied_at + timedelta(hours=1),
            source="credit_friendly_homes",
            medium="facebook_groups",
            campaign=saved.campaign,
            property_id=saved.property_id,
        ),
        ClickEvent(
            occurred_at=applied_at + timedelta(hours=2),
            source="credit_friendly_homes",
            medium="nextdoor",
            campaign="different_campaign",
            property_id=saved.property_id,
        ),
    ]
    events = [
        attribution_event(
            saved,
            DwelyxEventType.BUYER_REGISTERED,
            buyer_id="buyer-1",
            occurred_at=applied_at + timedelta(hours=3),
        ),
        attribution_event(
            saved,
            DwelyxEventType.APPLICATION_SUBMITTED,
            buyer_id="buyer-1",
            occurred_at=applied_at + timedelta(hours=4),
        ),
    ]
    metrics = phase_metrics(
        ledger,
        saved,
        TestPhase.CHALLENGER,
        click_events=clicks,
        attribution_events=events,
        now=NOW,
    )
    assert metrics.tracked_clicks == 1
    assert metrics.registrations == 1
    assert metrics.applications == 1


def test_recommendation_extends_until_minimum_sample() -> None:
    item = property_record()
    experiment = draft_experiment(item, minimum_test_days=7, minimum_clicks=10)
    applied_at = NOW - timedelta(days=2)
    ledger, _ = approve_and_apply(item, experiment, applied_at=applied_at)
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    result = recommendation_for_experiment(ledger, saved, now=NOW)
    assert result.recommendation == TermsRecommendation.EXTEND
    assert not result.sample_ready


def test_recommendation_keeps_challenger_when_rate_improves() -> None:
    item = property_record()
    experiment = draft_experiment(
        item,
        minimum_test_days=1,
        minimum_clicks=1,
        minimum_registrations=1,
    )
    applied_at = NOW - timedelta(days=10)
    ledger, _ = approve_and_apply(item, experiment, applied_at=applied_at)
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        phase=TestPhase.CONTROL,
        period_start=BASELINE_START,
        period_end=BASELINE_END,
        reported_clicks=20,
        registrations=4,
        applications=1,
        now=NOW,
    )
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        phase=TestPhase.CHALLENGER,
        period_start=(NOW - timedelta(days=10)).date(),
        period_end=NOW.date(),
        reported_clicks=20,
        registrations=8,
        applications=4,
        now=NOW,
    )
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    result = recommendation_for_experiment(ledger, saved, now=NOW)
    assert result.recommendation == TermsRecommendation.KEEP
    assert result.lift_percent >= 0.20


def test_recommendation_reverts_when_challenger_degrades() -> None:
    item = property_record()
    experiment = draft_experiment(
        item,
        minimum_test_days=1,
        minimum_clicks=1,
        minimum_registrations=1,
    )
    applied_at = NOW - timedelta(days=10)
    ledger, _ = approve_and_apply(item, experiment, applied_at=applied_at)
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        phase=TestPhase.CONTROL,
        period_start=BASELINE_START,
        period_end=BASELINE_END,
        reported_clicks=20,
        registrations=8,
        applications=4,
        now=NOW,
    )
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        phase=TestPhase.CHALLENGER,
        period_start=(NOW - timedelta(days=10)).date(),
        period_end=NOW.date(),
        reported_clicks=20,
        registrations=2,
        applications=1,
        now=NOW,
    )
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    result = recommendation_for_experiment(ledger, saved, now=NOW)
    assert result.recommendation == TermsRecommendation.REVERT
    assert result.lift_percent < 0


def test_signed_contract_overrides_other_recommendations() -> None:
    item = property_record()
    experiment = draft_experiment(item, minimum_test_days=1, minimum_clicks=1)
    applied_at = NOW - timedelta(days=10)
    ledger, _ = approve_and_apply(item, experiment, applied_at=applied_at)
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    events = [
        attribution_event(
            saved,
            DwelyxEventType.CONTRACT_SIGNED,
            buyer_id="buyer-contract",
            occurred_at=NOW - timedelta(hours=1),
        )
    ]
    result = recommendation_for_experiment(
        ledger,
        saved,
        attribution_events=events,
        now=NOW,
    )
    assert result.recommendation == TermsRecommendation.PROTECT_CONTRACT
    assert result.confidence == "High"


def test_keep_decision_completes_without_changing_property_again() -> None:
    item = property_record()
    experiment = draft_experiment(item)
    ledger, challenger_property = approve_and_apply(item, experiment)
    ledger = mark_review_ready(
        ledger,
        experiment_id=experiment.experiment_id,
        now=NOW,
    )
    ledger = approve_decision(
        ledger,
        experiment_id=experiment.experiment_id,
        decision=TermsRecommendation.KEEP,
        decided_by="Shawn",
        decision_reason="The challenger produced a stronger application rate.",
        now=NOW,
    )
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    assert saved.status == TermsExperimentStatus.COMPLETED
    assert challenger_property.down_payment == Decimal("1500")


def test_revert_requires_separate_approval_and_restores_original_terms() -> None:
    item = property_record()
    experiment = draft_experiment(item)
    ledger, challenger_property = approve_and_apply(item, experiment)
    ledger = approve_decision(
        ledger,
        experiment_id=experiment.experiment_id,
        decision=TermsRecommendation.REVERT,
        decided_by="Shawn",
        decision_reason="The challenger reduced qualified applications.",
        now=NOW,
    )
    saved = find_experiment(ledger, experiment.experiment_id)
    assert saved is not None
    assert saved.status == TermsExperimentStatus.REVERT_APPROVED
    assert challenger_property.down_payment == Decimal("1500")

    ledger, restored = rollback_to_control(
        ledger,
        challenger_property,
        experiment_id=experiment.experiment_id,
        rollback_by="Sabrina",
        now=NOW,
    )
    completed = find_experiment(ledger, experiment.experiment_id)
    assert completed is not None
    assert completed.status == TermsExperimentStatus.COMPLETED
    assert restored.down_payment == Decimal("2500")
    assert len(completed.relaunch_tasks) == 15
    assert all(task.operation == "Restore Original" for task in completed.relaunch_tasks)
