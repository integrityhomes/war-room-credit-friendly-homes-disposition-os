from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cfh_disposition.ai_campaign import build_fallback_campaign
from cfh_disposition.automatic_launch import channel_copy_with_link
from cfh_disposition.facebook_groups import (
    FacebookGroupError,
    FacebookGroupLedger,
    active_groups,
    deactivate_group,
    facebook_group_post_status,
    group_directory_rows,
    group_post_rows,
    record_facebook_group_post,
    upsert_group,
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
        total_price=Decimal("94500"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        condition_summary="Habitable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        showing_instructions="Appointment required.",
        public_disclosures="Possible updating.",
    )


def august_now(day: int = 4) -> datetime:
    return datetime(2026, 8, day, 16, 0, tzinfo=UTC)


def ledger_with_group(cooldown_days: int = 7) -> FacebookGroupLedger:
    return upsert_group(
        FacebookGroupLedger(),
        name="Owner Financing Homes for Sale",
        group_url="https://www.facebook.com/groups/123456",
        cooldown_days=cooldown_days,
        notes="Admin approval required.",
        now=august_now(),
    )


def test_group_directory_adds_and_updates_without_duplicates() -> None:
    ledger = ledger_with_group()
    assert len(ledger.groups) == 1
    assert ledger.groups[0].cooldown_days == 7

    ledger = upsert_group(
        ledger,
        name="Owner Financing Homes for Sale",
        group_url="https://facebook.com/groups/123456",
        cooldown_days=10,
        notes="Updated rules.",
        now=august_now(5),
    )

    assert len(ledger.groups) == 1
    assert ledger.groups[0].cooldown_days == 10
    assert ledger.groups[0].notes == "Updated rules."
    assert len(group_directory_rows(ledger)) == 1


def test_first_property_post_is_eligible_and_records_tracked_link() -> None:
    item = sample_property()
    ledger = ledger_with_group()
    group = active_groups(ledger)[0]
    status = facebook_group_post_status(
        ledger,
        property_id=item.property_id,
        group_id=group.group_id,
        now=august_now(),
    )
    assert status.eligible

    tracked_link = "https://tracking.example.com/?go=dwelyx&medium=facebook_groups"
    ledger = record_facebook_group_post(
        ledger,
        property_id=item.property_id,
        property_address=item.display_address,
        group_id=group.group_id,
        posted_by="Sabrina",
        campaign="decatur_owner_finance",
        tracked_link=tracked_link,
        notes="Approved by admin.",
        now=august_now(),
    )

    assert len(ledger.posts) == 1
    assert ledger.posts[0].tracked_link == tracked_link
    assert len(group_post_rows(ledger)) == 1


def test_same_property_group_repost_is_blocked_until_cooldown_ends() -> None:
    item = sample_property()
    ledger = ledger_with_group(cooldown_days=7)
    group = active_groups(ledger)[0]
    ledger = record_facebook_group_post(
        ledger,
        property_id=item.property_id,
        property_address=item.display_address,
        group_id=group.group_id,
        posted_by="Sabrina",
        campaign="owner_finance_homes",
        tracked_link="https://tracking.example.com/group",
        now=august_now(4),
    )

    blocked = facebook_group_post_status(
        ledger,
        property_id=item.property_id,
        group_id=group.group_id,
        now=august_now(8),
    )
    assert not blocked.eligible
    assert blocked.wait_days == 3

    with pytest.raises(FacebookGroupError, match="Do not repost"):
        record_facebook_group_post(
            ledger,
            property_id=item.property_id,
            property_address=item.display_address,
            group_id=group.group_id,
            posted_by="Sabrina",
            campaign="owner_finance_homes",
            tracked_link="https://tracking.example.com/group",
            now=august_now(8),
        )

    ready = facebook_group_post_status(
        ledger,
        property_id=item.property_id,
        group_id=group.group_id,
        now=august_now(11),
    )
    assert ready.eligible


def test_deactivated_group_cannot_receive_posts() -> None:
    item = sample_property()
    ledger = ledger_with_group()
    group = active_groups(ledger)[0]
    ledger = deactivate_group(ledger, group_id=group.group_id, now=august_now(5))

    assert active_groups(ledger) == []
    status = facebook_group_post_status(
        ledger,
        property_id=item.property_id,
        group_id=group.group_id,
        now=august_now(5),
    )
    assert not status.eligible
    assert "inactive" in status.message.lower()


def test_facebook_group_package_keeps_tracked_dwelyx_link() -> None:
    item = sample_property()
    original_link = "https://tracking.example.com/?go=dwelyx&medium=property_page"
    selected_link = "https://tracking.example.com/?go=dwelyx&medium=facebook_groups"
    package = build_fallback_campaign(item, original_link)

    copy = channel_copy_with_link(package, "facebook_groups", selected_link)

    assert selected_link in copy
    assert original_link not in copy
    assert "dwelyx" in copy.lower()
    assert item.address in copy
