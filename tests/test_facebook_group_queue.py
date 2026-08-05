from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfh_disposition.facebook_group_queue import (
    build_facebook_group_queue,
    eligible_queue_items,
    operator_current_item,
    operator_progress,
    queue_summary_rows,
)
from cfh_disposition.facebook_groups import (
    FacebookGroupLedger,
    deactivate_group,
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
        condition_summary="Livable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        showing_instructions="Appointment required.",
        public_disclosures="Possible updating.",
    )


def build_ledger() -> FacebookGroupLedger:
    ledger = upsert_group(
        FacebookGroupLedger(),
        name="Owner Financing Homes for Sale",
        group_url="https://www.facebook.com/groups/1305510733671893",
        cooldown_days=7,
        notes="Owner-financing properties only. No rentals.",
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )
    return upsert_group(
        ledger,
        name="Illinois Owner Finance Homes",
        group_url="https://www.facebook.com/groups/123456789",
        cooldown_days=3,
        notes="One post per property every three days.",
        now=datetime(2026, 8, 1, 12, 1, tzinfo=UTC),
    )


def test_queue_starts_with_every_active_group_ready() -> None:
    item = sample_property()
    queue = build_facebook_group_queue(
        build_ledger(),
        property_id=item.property_id,
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )

    assert len(queue) == 2
    assert len(eligible_queue_items(queue)) == 2
    assert all(row.eligible for row in queue)
    assert all(row.next_eligible_at is None for row in queue)
    assert all(row.notes for row in queue)
    summary = queue_summary_rows(queue)
    assert len(summary) == 2
    assert all(row["Group Rules / Notes"] != "—" for row in summary)


def test_queue_blocks_only_the_group_that_received_the_property() -> None:
    item = sample_property()
    ledger = build_ledger()
    first_group = ledger.groups[0]
    posted_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    ledger = record_facebook_group_post(
        ledger,
        property_id=item.property_id,
        property_address=item.display_address,
        group_id=first_group.group_id,
        posted_by="Sabrina",
        campaign="owner_finance_homes",
        tracked_link="https://tracking.example.com/group-one",
        now=posted_at,
    )

    queue = build_facebook_group_queue(
        ledger,
        property_id=item.property_id,
        now=posted_at + timedelta(days=1),
    )
    by_name = {row.group_name: row for row in queue}

    assert by_name[first_group.name].eligible is False
    assert by_name[first_group.name].wait_days == 6
    assert by_name[ledger.groups[1].name].eligible is True
    assert len(eligible_queue_items(queue)) == 1


def test_queue_reopens_group_after_cooldown() -> None:
    item = sample_property()
    ledger = build_ledger()
    group = ledger.groups[0]
    posted_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    ledger = record_facebook_group_post(
        ledger,
        property_id=item.property_id,
        property_address=item.display_address,
        group_id=group.group_id,
        posted_by="Sabrina",
        campaign="owner_finance_homes",
        tracked_link="https://tracking.example.com/group-one",
        now=posted_at,
    )

    queue = build_facebook_group_queue(
        ledger,
        property_id=item.property_id,
        now=posted_at + timedelta(days=7),
    )
    by_name = {row.group_name: row for row in queue}

    assert by_name[group.name].eligible is True
    assert by_name[group.name].wait_days == 0


def test_inactive_groups_do_not_appear_in_queue() -> None:
    item = sample_property()
    ledger = build_ledger()
    inactive = ledger.groups[1]
    ledger = deactivate_group(
        ledger,
        group_id=inactive.group_id,
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )

    queue = build_facebook_group_queue(
        ledger,
        property_id=item.property_id,
        now=datetime(2026, 8, 4, 12, 1, tzinfo=UTC),
    )

    assert len(queue) == 1
    assert queue[0].group_name != inactive.name


def test_operator_mode_wraps_cursor_and_reports_progress() -> None:
    item = sample_property()
    queue = build_facebook_group_queue(
        build_ledger(),
        property_id=item.property_id,
        now=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )

    first = operator_current_item(queue, 0)
    wrapped = operator_current_item(queue, 2)
    assert first is not None
    assert wrapped is not None
    assert wrapped.group_id == first.group_id
    assert operator_progress(queue, 0) == (1, 2)
    assert operator_progress(queue, 1) == (2, 2)
    assert operator_progress(queue, 2) == (1, 2)


def test_operator_mode_returns_empty_state_when_no_groups_are_ready() -> None:
    item = sample_property()
    ledger = build_ledger()
    posted_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    for group in ledger.groups:
        ledger = record_facebook_group_post(
            ledger,
            property_id=item.property_id,
            property_address=item.display_address,
            group_id=group.group_id,
            posted_by="Sabrina",
            campaign="owner_finance_homes",
            tracked_link=f"https://tracking.example.com/{group.group_id}",
            now=posted_at,
        )

    queue = build_facebook_group_queue(
        ledger,
        property_id=item.property_id,
        now=posted_at + timedelta(hours=1),
    )
    assert operator_current_item(queue, 0) is None
    assert operator_progress(queue, 0) == (0, 0)
