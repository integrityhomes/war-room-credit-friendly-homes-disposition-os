from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.creative_testing import (
    CreativeTestingError,
    CreativeTestingLedger,
    ExperimentStatus,
    VariantStatus,
    approve_winner,
    assigned_variant,
    build_creative_experiment,
    create_experiment,
    experiment_variant_metrics,
    mark_winner_ready,
    upsert_outcome,
    validate_variant_copy,
    winner_recommendation,
)
from cfh_disposition.models import OwnerFinanceProperty


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        square_feet=1352,
        total_price=Decimal("94500"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        condition_summary="Livable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        public_disclosures="Possible updating.",
    )


def build_test(channel_key: str = "email", primary_metric: str = "Tracked Dwelyx clicks"):
    return build_creative_experiment(
        sample_property(),
        "https://www.dwelyx.com/buyer/register",
        channel_key=channel_key,
        primary_metric=primary_metric,
        minimum_impressions_per_variant=100,
        minimum_clicks_per_variant=10,
        winner_lift_threshold=Decimal("0.20"),
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def add_variant_results(
    ledger: CreativeTestingLedger,
    experiment,
    clicks: list[int],
    *,
    inquiries: list[int] | None = None,
    applications: list[int] | None = None,
    contracts: list[int] | None = None,
) -> CreativeTestingLedger:
    inquiries = inquiries or [0] * len(experiment.variants)
    applications = applications or [0] * len(experiment.variants)
    contracts = contracts or [0] * len(experiment.variants)
    updated = ledger
    for index, variant in enumerate(experiment.variants):
        updated = upsert_outcome(
            updated,
            experiment_id=experiment.experiment_id,
            variant_id=variant.variant_id,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 7),
            impressions=1000,
            reported_clicks=clicks[index],
            inquiries=inquiries[index],
            applications=applications[index],
            contracts=contracts[index],
            spend=Decimal("25"),
            now=datetime(2026, 8, 8, 12, index, tzinfo=UTC),
        )
    return updated


def test_variants_preserve_facts_and_block_purchase_price() -> None:
    property_record = sample_property()
    experiment = build_test("facebook_groups")

    assert len(experiment.variants) == 4
    assert [variant.allocation_percent for variant in experiment.variants] == [25, 25, 25, 25]
    assert sum(variant.is_control for variant in experiment.variants) == 1
    for variant in experiment.variants:
        assert validate_variant_copy(variant, property_record) == []
        assert property_record.display_address in variant.copy
        assert "$2,000" in variant.copy
        assert "$950" in variant.copy
        assert "$94,500" not in variant.copy
        assert variant.copy.count(variant.tracked_link) == 1
        assert "not rent" in variant.copy.lower()
        assert "guaranteed approval" not in variant.copy.lower()
        assert "safe neighborhood" not in variant.copy.lower()


def test_marketplace_is_not_supported() -> None:
    with pytest.raises(CreativeTestingError, match="supported"):
        build_creative_experiment(
            sample_property(),
            "https://www.dwelyx.com/buyer/register",
            channel_key="marketplace",
        )


def test_duplicate_active_experiment_is_blocked() -> None:
    experiment = build_test()
    ledger = create_experiment(CreativeTestingLedger(), experiment)

    with pytest.raises(CreativeTestingError, match="active creative test"):
        create_experiment(ledger, build_test())


def test_outcome_upsert_replaces_same_variant_period() -> None:
    experiment = build_test()
    ledger = create_experiment(CreativeTestingLedger(), experiment)
    variant = experiment.variants[0]
    first = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        variant_id=variant.variant_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 7),
        impressions=100,
        reported_clicks=5,
    )
    second = upsert_outcome(
        first,
        experiment_id=experiment.experiment_id,
        variant_id=variant.variant_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 7),
        impressions=250,
        reported_clicks=12,
    )

    assert len(second.outcomes) == 1
    assert second.outcomes[0].impressions == 250
    assert second.outcomes[0].reported_clicks == 12


def test_tracked_clicks_are_attributed_by_variant_campaign() -> None:
    experiment = build_test()
    ledger = create_experiment(CreativeTestingLedger(), experiment)
    variant = experiment.variants[1]
    events = [
        ClickEvent(
            occurred_at=datetime(2026, 8, 4, 12, index, tzinfo=UTC),
            source="credit_friendly_homes",
            medium="email",
            campaign=variant.campaign,
            property_id=experiment.property_id,
        )
        for index in range(7)
    ]

    metrics = experiment_variant_metrics(ledger, experiment, events)
    selected = next(item for item in metrics if item.variant_id == variant.variant_id)

    assert selected.tracked_clicks == 7
    assert selected.usable_clicks == 7


def test_winner_waits_for_sample_size() -> None:
    experiment = build_test()
    ledger = create_experiment(CreativeTestingLedger(), experiment)
    ledger = upsert_outcome(
        ledger,
        experiment_id=experiment.experiment_id,
        variant_id=experiment.variants[0].variant_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 2),
        impressions=50,
        reported_clicks=20,
    )

    recommendation = winner_recommendation(ledger, experiment)

    assert recommendation.ready is False
    assert "minimum" in recommendation.reason.lower()


def test_click_winner_is_recommended_and_can_be_approved() -> None:
    experiment = build_test()
    ledger = create_experiment(CreativeTestingLedger(), experiment)
    ledger = add_variant_results(ledger, experiment, [50, 20, 18, 17])

    recommendation = winner_recommendation(ledger, experiment)
    assert recommendation.ready is True
    assert recommendation.winner_key == "A"
    assert recommendation.lift_percent > 100

    ready_ledger = mark_winner_ready(
        ledger,
        experiment_id=experiment.experiment_id,
        now=datetime(2026, 8, 8, 13, 0, tzinfo=UTC),
    )
    ready_experiment = ready_ledger.experiments[0]
    assert ready_experiment.status == ExperimentStatus.WINNER_READY
    assert ready_experiment.winner_variant_id == experiment.variants[0].variant_id

    approved_ledger = approve_winner(
        ready_ledger,
        experiment_id=experiment.experiment_id,
        approved_by="Sabrina",
        now=datetime(2026, 8, 8, 14, 0, tzinfo=UTC),
    )
    approved = approved_ledger.experiments[0]
    allocations = {variant.key: variant.allocation_percent for variant in approved.variants}

    assert approved.status == ExperimentStatus.WINNER_APPROVED
    assert approved.winner_approved_by == "Sabrina"
    assert allocations == {"A": 70, "B": 10, "C": 10, "D": 10}
    assert sum(allocations.values()) == 100
    assert approved.variants[0].status == VariantStatus.WINNER


def test_contract_metric_can_select_a_business_outcome_winner() -> None:
    experiment = build_test(primary_metric="Contracts")
    ledger = create_experiment(CreativeTestingLedger(), experiment)
    ledger = add_variant_results(
        ledger,
        experiment,
        [15, 15, 15, 15],
        contracts=[1, 0, 0, 0],
    )

    recommendation = winner_recommendation(ledger, experiment)

    assert recommendation.ready is True
    assert recommendation.winner_key == "A"


def test_assignment_is_deterministic_and_favors_approved_winner() -> None:
    experiment = build_test()
    ledger = create_experiment(CreativeTestingLedger(), experiment)
    ledger = add_variant_results(ledger, experiment, [50, 20, 18, 17])
    ledger = mark_winner_ready(ledger, experiment_id=experiment.experiment_id)
    ledger = approve_winner(
        ledger,
        experiment_id=experiment.experiment_id,
        approved_by="Sabrina",
    )
    approved = ledger.experiments[0]

    first = assigned_variant(approved, "buyer-123")
    second = assigned_variant(approved, "buyer-123")
    assert first.variant_id == second.variant_id

    assignments = [assigned_variant(approved, f"buyer-{index}").key for index in range(1000)]
    winner_count = assignments.count("A")
    assert 620 <= winner_count <= 780
