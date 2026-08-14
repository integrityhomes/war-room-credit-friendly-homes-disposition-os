from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.paid_traffic_channels import PaidTrafficPackageError, build_paid_traffic_package


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


def test_meta_and_google_get_distinct_tracked_links():
    property_ = property_record()
    rows = build_channel_links(
        "https://www.dwelyx.com/buyer/register",
        campaign="decatur_paid_launch",
        property_id=property_.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    by_key = {row["Channel key"]: row for row in rows}
    urls = [by_key[key]["Tracked Dwelyx link"] for key in ("meta_ads", "google_ads")]
    assert len(set(urls)) == 2
    for key, url in zip(("meta_ads", "google_ads"), urls, strict=True):
        query = parse_qs(urlsplit(url).query)
        assert query["medium"] == [key]
        assert query["campaign"] == ["decatur_paid_launch"]
        assert query["property_id"] == [str(property_.property_id)]


@pytest.mark.parametrize(
    ("channel_key", "channel_name"),
    [("meta_ads", "Meta Housing Ads"), ("google_ads", "Google Search Ads")],
)
def test_paid_package_preserves_verified_terms_without_public_total_price(channel_key, channel_name):
    package = build_paid_traffic_package(
        property_record(),
        channel_key=channel_key,
        channel_name=channel_name,
        tracked_link=f"https://tracking.example.com/?medium={channel_key}",
        campaign_name="decatur_paid_launch",
        daily_budget=Decimal("20"),
        monthly_budget_cap=Decimal("600"),
    )
    combined = " ".join((*package.headline_options, *package.primary_text_options, package.description))
    assert "945 W Packard St" in combined
    assert "$995" in combined
    assert "$3,500" in combined
    assert "$79,900" not in combined
    assert package.tracked_link.endswith(f"medium={channel_key}")
    assert package.daily_budget == Decimal("20")
    assert package.monthly_budget_cap == Decimal("600")


def test_paid_package_requires_address():
    property_ = OwnerFinanceProperty(city="Decatur", state="IL", monthly_payment=Decimal("995"))
    with pytest.raises(PaidTrafficPackageError, match="address"):
        build_paid_traffic_package(
            property_,
            channel_key="meta_ads",
            channel_name="Meta Housing Ads",
            tracked_link="https://tracking.example.com/?medium=meta_ads",
            campaign_name="test",
            daily_budget=Decimal("20"),
            monthly_budget_cap=Decimal("600"),
        )


def test_paid_package_rejects_bad_budget_relationship():
    with pytest.raises(PaidTrafficPackageError, match="monthly budget cap"):
        build_paid_traffic_package(
            property_record(),
            channel_key="google_ads",
            channel_name="Google Search Ads",
            tracked_link="https://tracking.example.com/?medium=google_ads",
            campaign_name="test",
            daily_budget=Decimal("100"),
            monthly_budget_cap=Decimal("500"),
        )


def test_paid_package_rejects_unsupported_channel():
    with pytest.raises(PaidTrafficPackageError, match="Unsupported paid channel"):
        build_paid_traffic_package(
            property_record(),
            channel_key="instagram",
            channel_name="Instagram",
            tracked_link="https://tracking.example.com/?medium=instagram",
            campaign_name="test",
            daily_budget=Decimal("20"),
            monthly_budget_cap=Decimal("600"),
        )
