from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.classifieds_channel import (
    ClassifiedsPackageError,
    build_classifieds_package,
)
from cfh_disposition.models import OwnerFinanceProperty


def property_record() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("79900"),
        down_payment=Decimal("3500"),
        monthly_payment=Decimal("995"),
        condition_summary="Property is presented in its current as-is condition.",
        repairs_needed="Cosmetic repairs are visible in the current property media.",
    )


def test_classifieds_package_preserves_verified_property_facts():
    property_ = property_record()
    package = build_classifieds_package(
        property_,
        tracked_link="https://tracking.example.com/?medium=classifieds",
    )

    assert package.channel_key == "classifieds"
    assert len(package.body_variants) == 3
    assert package.headline == "Owner-Finance Home Available in Decatur, IL"
    for body in package.body_variants:
        assert "945 W Packard St" in body
        assert "$995" in body
        assert "$3,500" in body
        assert "$79,900" in body
        assert "current as-is condition" in body
        assert "https://tracking.example.com/?medium=classifieds" in body


def test_classifieds_uses_channel_campaign_and_property_tracking():
    property_ = property_record()
    rows = build_channel_links(
        "https://www.dwelyx.com/buyer/register",
        campaign="decatur_classifieds_launch",
        property_id=property_.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    row = next(item for item in rows if item["Channel key"] == "classifieds")
    query = parse_qs(urlsplit(row["Tracked Dwelyx link"]).query)

    assert query["medium"] == ["classifieds"]
    assert query["campaign"] == ["decatur_classifieds_launch"]
    assert query["property_id"] == [str(property_.property_id)]


def test_classifieds_package_blocks_missing_street_address():
    property_ = OwnerFinanceProperty(
        city="Decatur",
        state="IL",
        total_price=Decimal("79900"),
    )
    with pytest.raises(ClassifiedsPackageError, match="street address"):
        build_classifieds_package(
            property_,
            tracked_link="https://tracking.example.com/?medium=classifieds",
        )


def test_classifieds_package_blocks_missing_terms():
    property_ = OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
    )
    with pytest.raises(ClassifiedsPackageError, match="monthly payment or total price"):
        build_classifieds_package(
            property_,
            tracked_link="https://tracking.example.com/?medium=classifieds",
        )


def test_classifieds_package_blocks_missing_tracked_link():
    with pytest.raises(ClassifiedsPackageError, match="tracked Dwelyx link"):
        build_classifieds_package(property_record(), tracked_link="")
