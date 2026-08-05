from datetime import UTC, datetime
from decimal import Decimal

from cfh_disposition.ai_campaign import build_fallback_campaign
from cfh_disposition.campaign_launch import (
    LaunchStatus,
    approve_all_channels,
    campaign_copy_for_channel,
    campaign_slug,
    launch_object_path,
    launch_rows,
    new_launch_state,
    set_channel_status,
)
from cfh_disposition.channels import CHANNELS
from cfh_disposition.models import OwnerFinanceProperty


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="101 Test Street",
        city="Bristol",
        state="VA",
        zip_code="24201",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("100000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
        condition_summary="Habitable property sold as-is.",
        repairs_needed="Kitchen updates are needed.",
        showing_instructions="Appointment required.",
        public_disclosures="Terms and availability are subject to verification.",
    )


def test_new_launch_state_contains_all_15_channels():
    now = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)
    state = new_launch_state("property-123", "August Bristol Homes", now=now)

    assert state.campaign == "august_bristol_homes"
    assert len(state.channels) == len(CHANNELS) == 15
    assert all(record.status == LaunchStatus.NOT_STARTED for record in state.channels.values())
    assert len(launch_rows(state)) == 15
    assert "nextdoor" in state.channels


def test_approve_all_and_update_one_channel():
    now = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)
    state = approve_all_channels(
        new_launch_state("property-123", "summer", now=now),
        approved_by="Sabrina",
        now=now,
    )

    assert all(record.status == LaunchStatus.READY for record in state.channels.values())
    assert state.approved_by == "Sabrina"

    updated = set_channel_status(
        state,
        "marketplace",
        LaunchStatus.POSTED,
        updated_by="Sabrina",
        notes="Posted to Marketplace listing 123.",
        now=now,
    )
    assert updated.channels["marketplace"].status == LaunchStatus.POSTED
    assert updated.channels["marketplace"].notes == "Posted to Marketplace listing 123."
    assert updated.channels["sms"].status == LaunchStatus.READY
    assert updated.channels["nextdoor"].status == LaunchStatus.READY


def test_marketplace_copy_excludes_all_external_links():
    item = sample_property()
    original_link = "https://tracking.example.com/?go=dwelyx&medium=property_page"
    selected_link = "https://tracking.example.com/?go=dwelyx&medium=marketplace"
    package = build_fallback_campaign(item, original_link)

    copy = campaign_copy_for_channel(package, "marketplace", selected_link)

    assert selected_link not in copy
    assert original_link not in copy
    assert "https://" not in copy
    assert "dwelyx" not in copy.lower()
    assert "Facebook Marketplace message" in copy
    assert item.address in copy


def test_facebook_group_copy_uses_selected_dwelyx_link():
    item = sample_property()
    original_link = "https://tracking.example.com/?go=dwelyx&medium=property_page"
    selected_link = "https://tracking.example.com/?go=dwelyx&medium=facebook_groups"
    package = build_fallback_campaign(item, original_link)

    copy = campaign_copy_for_channel(package, "facebook_groups", selected_link)

    assert selected_link in copy
    assert original_link not in copy
    assert "dwelyx" in copy.lower()
    assert item.address in copy


def test_nextdoor_copy_uses_selected_dwelyx_link_and_property_facts():
    item = sample_property()
    original_link = "https://tracking.example.com/?go=dwelyx&medium=property_page"
    selected_link = "https://tracking.example.com/?go=dwelyx&medium=nextdoor"
    package = build_fallback_campaign(item, original_link)

    copy = campaign_copy_for_channel(package, "nextdoor", selected_link)

    assert selected_link in copy
    assert original_link not in copy
    assert item.address in copy
    assert "$5,000" in copy
    assert "$1,200" in copy
    assert "subject to review and verification" in copy.lower()


def test_email_package_keeps_subject_and_replaces_tracking_link():
    item = sample_property()
    package = build_fallback_campaign(
        item,
        "https://tracking.example.com/?go=dwelyx&medium=property_page",
    )
    selected_link = "https://tracking.example.com/?go=dwelyx&medium=email"

    copy = campaign_copy_for_channel(package, "email", selected_link)

    assert copy.startswith("Subject:")
    assert selected_link in copy
    assert "medium=property_page" not in copy


def test_campaign_slug_and_storage_path_are_safe():
    assert campaign_slug(" August Bristol Homes!!! ") == "august_bristol_homes"
    assert (
        launch_object_path("property-123", " August Bristol Homes!!! ")
        == "launches/property-123/august_bristol_homes.json"
    )
