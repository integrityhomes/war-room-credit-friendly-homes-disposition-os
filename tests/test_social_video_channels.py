from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.social_video_channels import (
    SocialVideoPackageError,
    build_social_video_package,
)


def property_fixture() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("79900"),
        down_payment=Decimal("3500"),
        monthly_payment=Decimal("895"),
        condition_summary="Home is sold as-is in its current condition.",
    )


def test_social_channels_receive_separate_tracked_links():
    property_ = property_fixture()
    rows = build_channel_links(
        "https://www.dwelyx.com/buyer/register",
        campaign="decatur_social_august",
        property_id=property_.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    links = {row["Channel key"]: row["Tracked Dwelyx link"] for row in rows}

    selected = {key: links[key] for key in ("instagram", "tiktok", "youtube")}
    assert len(set(selected.values())) == 3

    for key, link in selected.items():
        query = parse_qs(urlsplit(link).query)
        assert query["medium"] == [key]
        assert query["campaign"] == ["decatur_social_august"]
        assert query["property_id"] == [str(property_.property_id)]


def test_social_package_uses_verified_property_facts_and_tracked_link():
    property_ = property_fixture()
    link = "https://tracking.example.com/?go=dwelyx&medium=instagram&campaign=decatur"

    package = build_social_video_package(
        property_,
        channel_key="instagram",
        channel_name="Instagram Reels & Posts",
        tracked_link=link,
    )

    assert "945 W Packard St" in package.caption
    assert "$895" in package.caption
    assert "$3,500" in package.caption
    assert "sold as-is" in package.caption
    assert package.tracked_link == link
    assert package.channel_key == "instagram"


def test_social_package_requires_address_and_real_marketing_terms():
    missing_address = OwnerFinanceProperty(
        city="Decatur",
        state="IL",
        monthly_payment=Decimal("895"),
    )
    with pytest.raises(SocialVideoPackageError, match="address"):
        build_social_video_package(
            missing_address,
            channel_key="tiktok",
            channel_name="TikTok",
            tracked_link="https://tracking.example.com",
        )

    missing_terms = OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
    )
    with pytest.raises(SocialVideoPackageError, match="monthly payment or total price"):
        build_social_video_package(
            missing_terms,
            channel_key="youtube",
            channel_name="YouTube Shorts",
            tracked_link="https://tracking.example.com",
        )
