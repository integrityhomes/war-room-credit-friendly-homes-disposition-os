from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.social_video_channels import (
    SocialVideoPackageError,
    build_social_video_package,
)


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
    )


def test_social_channels_get_distinct_tracked_links():
    property_ = property_record()
    rows = build_channel_links(
        "https://www.dwelyx.com/buyer/register",
        campaign="decatur_social_launch",
        property_id=property_.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    by_key = {row["Channel key"]: row for row in rows}

    urls = [by_key[key]["Tracked Dwelyx link"] for key in ("instagram", "tiktok", "youtube")]
    assert len(set(urls)) == 3

    for key, url in zip(("instagram", "tiktok", "youtube"), urls, strict=True):
        query = parse_qs(urlsplit(url).query)
        assert query["medium"] == [key]
        assert query["campaign"] == ["decatur_social_launch"]
        assert query["property_id"] == [str(property_.property_id)]


@pytest.mark.parametrize(
    ("channel_key", "channel_name"),
    [
        ("instagram", "Instagram Reels & Posts"),
        ("tiktok", "TikTok"),
        ("youtube", "YouTube Shorts"),
    ],
)
def test_social_package_uses_verified_property_facts_and_tracked_link(channel_key, channel_name):
    property_ = property_record()
    link = f"https://tracking.example.com/?medium={channel_key}"
    package = build_social_video_package(
        property_,
        channel_key=channel_key,
        channel_name=channel_name,
        tracked_link=link,
    )

    assert package.channel_key == channel_key
    assert package.channel_name == channel_name
    assert "945 W Packard St" in package.caption
    assert "Decatur" in package.caption
    assert "$995" in package.caption
    assert "$3,500" in package.caption
    assert "$79,900" in package.caption
    assert link in package.caption
    assert package.tracked_link == link
    assert len(package.shot_list) >= 5


def test_social_package_blocks_missing_property_address():
    property_ = OwnerFinanceProperty(
        city="Decatur",
        state="IL",
        total_price=Decimal("79900"),
    )

    with pytest.raises(SocialVideoPackageError, match="address"):
        build_social_video_package(
            property_,
            channel_key="instagram",
            channel_name="Instagram Reels & Posts",
            tracked_link="https://tracking.example.com/?medium=instagram",
        )


def test_social_package_blocks_missing_terms_and_price():
    property_ = OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
    )

    with pytest.raises(SocialVideoPackageError, match="monthly payment or total price"):
        build_social_video_package(
            property_,
            channel_key="youtube",
            channel_name="YouTube Shorts",
            tracked_link="https://tracking.example.com/?medium=youtube",
        )
