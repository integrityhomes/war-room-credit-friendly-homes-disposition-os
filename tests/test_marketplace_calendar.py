from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cfh_disposition.marketplace_calendar import (
    MarketplaceCalendarError,
    MarketplaceLedger,
    MarketplaceListingType,
    close_marketplace_listing,
    current_month_listings,
    marketplace_month_status,
    record_marketplace_listing,
)
from cfh_disposition.models import OwnerFinanceProperty


def sample_property(number: int = 1) -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address=f"{number} Test Street",
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


def august_now(day: int = 3) -> datetime:
    return datetime(2026, 8, day, 15, 0, tzinfo=UTC)


def test_monthly_status_explains_reset_and_remaining_slots() -> None:
    status = marketplace_month_status(MarketplaceLedger(), now=august_now())
    assert status.used == 0
    assert status.remaining == 5
    assert status.blocked is False
    assert status.reset_at.year == 2026
    assert status.reset_at.month == 9
    assert status.reset_at.day == 1
    assert status.wait_days == 29
    assert status.required_listing_type == MarketplaceListingType.FOR_SALE
    assert "5 of 5" in status.message
    assert "slots remaining" in status.message
    assert "sales, not rentals" in status.message


def test_different_owner_finance_properties_can_each_be_listed_for_sale() -> None:
    first = sample_property(1)
    second = sample_property(2)
    ledger = record_marketplace_listing(
        MarketplaceLedger(),
        property_id=first.property_id,
        address=first.display_address,
        listing_type=MarketplaceListingType.FOR_SALE,
        created_by="Sabrina",
        now=august_now(),
    )

    ledger = record_marketplace_listing(
        ledger,
        property_id=second.property_id,
        address=second.display_address,
        listing_type=MarketplaceListingType.FOR_SALE,
        created_by="Sabrina",
        now=august_now(4),
    )
    assert len(current_month_listings(ledger, august_now())) == 2
    assert all(
        item.listing_type == MarketplaceListingType.FOR_SALE
        for item in ledger.listings
    )


def test_owner_finance_property_cannot_be_recorded_as_for_rent() -> None:
    item = sample_property()
    with pytest.raises(MarketplaceCalendarError, match="must be listed under For Sale"):
        record_marketplace_listing(
            MarketplaceLedger(),
            property_id=item.property_id,
            address=item.display_address,
            listing_type=MarketplaceListingType.FOR_RENT,
            created_by="Sabrina",
            now=august_now(),
        )


def test_same_active_property_cannot_be_posted_twice() -> None:
    item = sample_property()
    ledger = record_marketplace_listing(
        MarketplaceLedger(),
        property_id=item.property_id,
        address=item.display_address,
        listing_type=MarketplaceListingType.FOR_SALE,
        created_by="Sabrina",
        now=august_now(),
    )

    status = marketplace_month_status(
        ledger,
        property_id=item.property_id,
        now=august_now(),
    )
    assert status.active_duplicate is not None

    with pytest.raises(MarketplaceCalendarError, match="already has an active"):
        record_marketplace_listing(
            ledger,
            property_id=item.property_id,
            address=item.display_address,
            listing_type=MarketplaceListingType.FOR_SALE,
            created_by="Sabrina",
            now=august_now(4),
        )


def test_closing_listing_does_not_restore_monthly_slot() -> None:
    item = sample_property()
    ledger = record_marketplace_listing(
        MarketplaceLedger(),
        property_id=item.property_id,
        address=item.display_address,
        listing_type=MarketplaceListingType.FOR_SALE,
        created_by="Sabrina",
        now=august_now(),
    )
    listing_id = ledger.listings[0].listing_id
    ledger = close_marketplace_listing(
        ledger,
        listing_id=listing_id,
        closed_by="Sabrina",
        now=august_now(5),
    )
    status = marketplace_month_status(ledger, now=august_now(5))
    assert status.used == 1
    assert status.remaining == 4
    assert ledger.listings[0].active is False


def test_fifth_listing_locks_ad_creation_until_next_month() -> None:
    ledger = MarketplaceLedger()
    for number in range(1, 6):
        item = sample_property(number)
        ledger = record_marketplace_listing(
            ledger,
            property_id=item.property_id,
            address=item.display_address,
            listing_type=MarketplaceListingType.FOR_SALE,
            created_by="Sabrina",
            now=august_now(number),
        )

    status = marketplace_month_status(ledger, now=august_now(6))
    assert status.used == 5
    assert status.remaining == 0
    assert status.blocked is True
    assert "monthly limit reached" in status.message.lower()
    assert "September 1, 2026" in status.message

    extra = sample_property(6)
    with pytest.raises(MarketplaceCalendarError, match="monthly limit reached"):
        record_marketplace_listing(
            ledger,
            property_id=extra.property_id,
            address=extra.display_address,
            listing_type=MarketplaceListingType.FOR_SALE,
            created_by="Sabrina",
            now=august_now(6),
        )
