from datetime import UTC, date, datetime
from decimal import Decimal

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.marketing_optimizer import (
    AIMarketingPlan,
    MarketingChannelDecision,
    MarketingCreativeTest,
    MarketingOptimizerLedger,
    MarketingPropertyPriority,
    RecommendationAction,
    build_channel_performance,
    build_fallback_marketing_plan,
    clicks_in_period,
    recommendation_for_metrics,
    records_in_period,
    upsert_performance_record,
    validate_ai_marketing_plan,
)
from cfh_disposition.models import OwnerFinanceProperty


def sample_property(number: int = 1) -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address=f"{944 + number} W Packard St",
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
        showing_instructions="Appointment required.",
        public_disclosures="Possible updating.",
    )


def test_upsert_replaces_same_property_channel_and_period() -> None:
    item = sample_property()
    ledger = upsert_performance_record(
        MarketingOptimizerLedger(),
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 4),
        property_id=str(item.property_id),
        property_address=item.display_address,
        channel_key="facebook_groups",
        impressions=100,
        reported_clicks=4,
        inquiries=1,
        spend="20",
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )
    updated = upsert_performance_record(
        ledger,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 4),
        property_id=str(item.property_id),
        property_address=item.display_address,
        channel_key="facebook_groups",
        impressions=200,
        reported_clicks=10,
        inquiries=3,
        spend="40",
        now=datetime(2026, 8, 4, 13, 0, tzinfo=UTC),
    )

    assert len(updated.records) == 1
    assert updated.records[0].impressions == 200
    assert updated.records[0].reported_clicks == 10
    assert updated.records[0].inquiries == 3
    assert updated.records[0].spend == Decimal("40")


def test_channel_performance_uses_higher_reported_or_tracked_click_count() -> None:
    item = sample_property()
    ledger = upsert_performance_record(
        MarketingOptimizerLedger(),
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 4),
        property_id=str(item.property_id),
        property_address=item.display_address,
        channel_key="facebook_groups",
        impressions=1000,
        reported_clicks=8,
        inquiries=0,
        spend="0",
    )
    events = [
        ClickEvent(
            occurred_at=datetime(2026, 8, 4, 12, index, tzinfo=UTC),
            source="credit_friendly_homes",
            medium="facebook_groups",
            campaign="owner_finance_homes",
            property_id=str(item.property_id),
        )
        for index in range(20)
    ]
    performance = build_channel_performance(ledger.records, events)
    facebook = next(
        row for row in performance if row.channel_key == "facebook_groups"
    )

    assert facebook.reported_clicks == 8
    assert facebook.tracked_clicks == 20
    assert facebook.usable_clicks == 20
    assert facebook.action == RecommendationAction.REPAIR
    assert facebook.click_to_inquiry_rate == 0


def test_recommendation_pauses_spend_without_inquiries() -> None:
    action, reason, confidence = recommendation_for_metrics(
        impressions=1000,
        usable_clicks=12,
        inquiries=0,
        applications=0,
        contracts=0,
        spend=Decimal("175"),
    )

    assert action == RecommendationAction.PAUSE
    assert "spend" in reason.lower()
    assert confidence == "High"


def test_recommendation_scales_a_channel_with_contracts() -> None:
    action, _, confidence = recommendation_for_metrics(
        impressions=200,
        usable_clicks=30,
        inquiries=8,
        applications=3,
        contracts=1,
        spend=Decimal("75"),
    )

    assert action == RecommendationAction.SCALE
    assert confidence == "High"


def test_period_filters_records_and_clicks_by_property() -> None:
    first = sample_property(1)
    second = sample_property(2)
    ledger = MarketingOptimizerLedger()
    for item, channel in [(first, "email"), (second, "sms")]:
        ledger = upsert_performance_record(
            ledger,
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 4),
            property_id=str(item.property_id),
            property_address=item.display_address,
            channel_key=channel,
            inquiries=1,
        )
    events = [
        ClickEvent(
            occurred_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
            source="credit_friendly_homes",
            medium="email",
            campaign="owner_finance_homes",
            property_id=str(first.property_id),
        ),
        ClickEvent(
            occurred_at=datetime(2026, 8, 3, 12, 1, tzinfo=UTC),
            source="credit_friendly_homes",
            medium="sms",
            campaign="owner_finance_homes",
            property_id=str(second.property_id),
        ),
    ]
    wanted = {str(first.property_id)}

    filtered_records = records_in_period(
        ledger,
        date(2026, 8, 1),
        date(2026, 8, 4),
        wanted,
    )
    filtered_clicks = clicks_in_period(
        events,
        date(2026, 8, 1),
        date(2026, 8, 4),
        wanted,
    )

    assert len(filtered_records) == 1
    assert filtered_records[0].property_id == str(first.property_id)
    assert len(filtered_clicks) == 1
    assert filtered_clicks[0].property_id == str(first.property_id)


def test_fallback_plan_preserves_properties_and_avoids_prohibited_claims() -> None:
    first = sample_property(1)
    second = sample_property(2)
    events = [
        ClickEvent(
            occurred_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
            source="credit_friendly_homes",
            medium="facebook_groups",
            campaign="owner_finance_homes",
            property_id=str(first.property_id),
        )
    ]
    performance = build_channel_performance([], events)
    plan = build_fallback_marketing_plan(
        [first, second],
        performance,
        events,
    )
    errors = validate_ai_marketing_plan(plan, [first, second])
    combined = plan.model_dump_json().lower()

    assert errors == []
    assert first.display_address.lower() in combined
    assert second.display_address.lower() in combined
    assert "guaranteed approval" not in combined
    assert "safe neighborhood" not in combined
    assert len(plan.channel_decisions) == 15
    assert any(decision.channel_key == "nextdoor" for decision in plan.channel_decisions)
    assert len(plan.creative_tests) >= 1


def test_plan_guard_blocks_property_address_mismatch_and_bad_metric() -> None:
    item = sample_property()
    plan = AIMarketingPlan(
        executive_summary=(
            "Use measured campaign outcomes to decide which channel should receive the next controlled test."
        ),
        immediate_actions=["Keep collecting accurate source and outcome data."],
        channel_decisions=[
            MarketingChannelDecision(
                channel_key="email",
                action="Keep Running",
                reason="The current data does not justify a major change yet.",
                seven_day_test="Change one subject line and compare tracked buyer activity.",
            )
        ],
        property_priorities=[
            MarketingPropertyPriority(
                property_id=str(item.property_id),
                property_address="Wrong Address",
                priority="High",
                reason="This is intentionally incorrect for the guard test.",
                primary_channel="email",
                secondary_channel="sms",
            )
        ],
        creative_tests=[
            MarketingCreativeTest(
                channel_key="email",
                test_name="Subject line test",
                control_angle="Use the existing factual subject line.",
                challenger_angle="Lead with exact owner-finance payment terms.",
                primary_metric="Likes",
                stop_rule="Review after seven days and stop the weaker version.",
            )
        ],
        measurement_gaps=[],
    )
    errors = validate_ai_marketing_plan(plan, [item])

    assert any("address mismatch" in error.lower() for error in errors)
    assert any("unsupported" in error.lower() for error in errors)
