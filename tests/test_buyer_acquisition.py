from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.buyer_acquisition import (
    AcquisitionCampaignStatus,
    AcquisitionRecommendation,
    BuyerAcquisitionError,
    BuyerAcquisitionLedger,
    build_acquisition_campaign,
    build_acquisition_performance,
    create_campaign,
    projected_registrations,
    recommend_budget_allocation,
    recommendation_for_acquisition,
    update_campaign_status,
    upsert_outcome,
    validate_campaign_copy,
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


def build_campaign(source_key: str = "meta_ads", property_specific: bool = True):
    return build_acquisition_campaign(
        source_key=source_key,
        market_city="Decatur",
        market_state="IL",
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        weekly_budget=Decimal("200"),
        target_cost_per_registration=Decimal("20"),
        weekly_registration_goal=10,
        property_record=sample_property() if property_specific else None,
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def test_property_campaign_preserves_facts_and_hides_total_price() -> None:
    property_record = sample_property()
    campaign = build_acquisition_campaign(
        source_key="meta_ads",
        market_city="Decatur",
        market_state="IL",
        dwelyx_url="https://www.dwelyx.com/buyer/register",
        property_record=property_record,
    )
    combined = "\n".join(
        [campaign.headline, campaign.primary_copy, campaign.short_video_hook, campaign.call_to_action]
    )

    assert validate_campaign_copy(campaign, property_record) == []
    assert property_record.display_address in combined
    assert "$2,000" in combined
    assert "$950" in combined
    assert "$94,500" not in combined
    assert combined.count(campaign.tracked_link) == 3
    assert "not rent" in combined.lower()
    assert "equal housing opportunity" in combined.lower()
    assert "guaranteed approval" not in combined.lower()


def test_market_campaign_grows_dwelyx_list_without_inventing_inventory() -> None:
    campaign = build_campaign("market_seo", property_specific=False)
    combined = "\n".join([campaign.primary_copy, campaign.short_video_hook, campaign.call_to_action])

    assert validate_campaign_copy(campaign) == []
    assert "Decatur, IL" in combined
    assert "as they become available" in combined
    assert "inventory and terms change" in combined.lower()
    assert campaign.property_id == ""
    assert combined.count(campaign.tracked_link) == 3


def test_protected_or_deceptive_audience_targeting_is_blocked() -> None:
    with pytest.raises(BuyerAcquisitionError, match="Prohibited housing audience"):
        build_acquisition_campaign(
            source_key="meta_ads",
            market_city="Decatur",
            market_state="IL",
            dwelyx_url="https://www.dwelyx.com/buyer/register",
            audience_notes="Target families only in a safe neighborhood.",
        )


def test_duplicate_active_source_and_scope_is_blocked() -> None:
    campaign = build_campaign(property_specific=False)
    ledger = create_campaign(BuyerAcquisitionLedger(), campaign)

    with pytest.raises(BuyerAcquisitionError, match="already exists"):
        create_campaign(ledger, build_campaign(property_specific=False))


def test_campaign_requires_manager_approval_before_live() -> None:
    campaign = build_campaign()
    ledger = create_campaign(BuyerAcquisitionLedger(), campaign)

    with pytest.raises(BuyerAcquisitionError, match="Approve"):
        update_campaign_status(
            ledger,
            campaign_id=campaign.campaign_id,
            status=AcquisitionCampaignStatus.LIVE,
            actor="Sabrina",
        )

    approved = update_campaign_status(
        ledger,
        campaign_id=campaign.campaign_id,
        status=AcquisitionCampaignStatus.APPROVED,
        actor="Sabrina",
        now=datetime(2026, 8, 4, 13, 0, tzinfo=UTC),
    )
    live = update_campaign_status(
        approved,
        campaign_id=campaign.campaign_id,
        status=AcquisitionCampaignStatus.LIVE,
        actor="Sabrina",
        now=datetime(2026, 8, 4, 14, 0, tzinfo=UTC),
    )

    assert approved.campaigns[0].approved_by == "Sabrina"
    assert live.campaigns[0].status == AcquisitionCampaignStatus.LIVE


def test_outcome_upsert_replaces_matching_campaign_period() -> None:
    campaign = build_campaign()
    ledger = create_campaign(BuyerAcquisitionLedger(), campaign)
    first = upsert_outcome(
        ledger,
        campaign_id=campaign.campaign_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 7),
        impressions=1000,
        reported_clicks=25,
        registrations=5,
        qualified_buyers=2,
        applications=1,
        spend=Decimal("100"),
    )
    updated = upsert_outcome(
        first,
        campaign_id=campaign.campaign_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 7),
        impressions=1500,
        reported_clicks=40,
        registrations=8,
        qualified_buyers=5,
        applications=2,
        spend=Decimal("140"),
    )

    assert len(updated.outcomes) == 1
    assert updated.outcomes[0].impressions == 1500
    assert updated.outcomes[0].registrations == 8
    assert updated.outcomes[0].qualified_buyers == 5


def test_tracked_dwelyx_clicks_are_attributed_to_campaign() -> None:
    campaign = build_campaign("google_ads", property_specific=False)
    ledger = create_campaign(BuyerAcquisitionLedger(), campaign)
    events = [
        ClickEvent(
            occurred_at=datetime(2026, 8, 4, 12, index, tzinfo=UTC),
            source="credit_friendly_homes",
            medium="google_ads",
            campaign=campaign.campaign_code,
        )
        for index in range(12)
    ]
    performance = build_acquisition_performance(ledger, events)

    assert performance[0].tracked_clicks == 12
    assert performance[0].usable_clicks == 12


def test_acquisition_recommendations_focus_on_business_outcomes() -> None:
    scale, _, scale_confidence = recommendation_for_acquisition(
        usable_clicks=40,
        registrations=8,
        qualified_buyers=5,
        applications=2,
        contracts=0,
        spend=Decimal("120"),
        target_cost_per_registration=Decimal("20"),
    )
    pause, _, pause_confidence = recommendation_for_acquisition(
        usable_clicks=30,
        registrations=0,
        qualified_buyers=0,
        applications=0,
        contracts=0,
        spend=Decimal("100"),
        target_cost_per_registration=Decimal("20"),
    )
    contract_scale, _, _ = recommendation_for_acquisition(
        usable_clicks=10,
        registrations=2,
        qualified_buyers=1,
        applications=1,
        contracts=1,
        spend=Decimal("200"),
        target_cost_per_registration=Decimal("20"),
    )

    assert scale == AcquisitionRecommendation.SCALE
    assert scale_confidence == "High"
    assert pause == AcquisitionRecommendation.PAUSE
    assert pause_confidence == "High"
    assert contract_scale == AcquisitionRecommendation.SCALE


def test_budget_allocation_sums_to_total_and_gives_paused_campaign_zero() -> None:
    scale_campaign = build_campaign("meta_ads", property_specific=False)
    pause_campaign = build_campaign("google_ads", property_specific=False)
    ledger = create_campaign(BuyerAcquisitionLedger(), scale_campaign)
    ledger = create_campaign(ledger, pause_campaign)
    for campaign in [scale_campaign, pause_campaign]:
        ledger = update_campaign_status(
            ledger,
            campaign_id=campaign.campaign_id,
            status=AcquisitionCampaignStatus.APPROVED,
            actor="Sabrina",
        )
    ledger = upsert_outcome(
        ledger,
        campaign_id=scale_campaign.campaign_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 7),
        impressions=1000,
        reported_clicks=40,
        registrations=8,
        qualified_buyers=5,
        applications=2,
        spend=Decimal("120"),
    )
    ledger = upsert_outcome(
        ledger,
        campaign_id=pause_campaign.campaign_id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 7),
        impressions=1000,
        reported_clicks=30,
        registrations=0,
        spend=Decimal("100"),
    )
    performance = build_acquisition_performance(ledger)
    allocations = recommend_budget_allocation(
        ledger.campaigns,
        performance,
        Decimal("500"),
    )
    by_campaign = {row.campaign_id: row for row in allocations}

    assert sum((row.recommended_weekly_budget for row in allocations), Decimal("0")) == Decimal("500.00")
    assert by_campaign[scale_campaign.campaign_id].recommended_weekly_budget == Decimal("500.00")
    assert by_campaign[pause_campaign.campaign_id].recommended_weekly_budget == Decimal("0")


def test_registration_projection_uses_saved_cost_target() -> None:
    assert projected_registrations(Decimal("500"), Decimal("20")) == 25
    assert projected_registrations(Decimal("0"), Decimal("20")) == 0
