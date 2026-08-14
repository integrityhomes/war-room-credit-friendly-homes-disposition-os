from decimal import Decimal

import pytest

from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.owned_web_channels import OwnedWebPackageError, build_owned_web_package


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        monthly_payment=Decimal("995"),
        down_payment=Decimal("2500"),
    )


def test_owned_web_channels_keep_separate_attribution():
    property_ = sample_property()
    links = build_channel_links(
        "https://dwelyx.example",
        campaign="decatur_owned_web",
        property_id=property_.property_id,
        tracking_base_url="https://cfh.example",
    )
    links_by_key = {row["Channel key"]: row["Tracked Dwelyx link"] for row in links}

    packages = {
        key: build_owned_web_package(
            property_,
            channel_key=key,
            channel_name=key,
            tracked_link=links_by_key[key],
        )
        for key in ("property_page", "blog", "market_seo")
    }

    assert len({package.tracked_link for package in packages.values()}) == 3
    assert "945 W Packard St" in packages["property_page"].body
    assert "Decatur, IL" in packages["blog"].body
    assert "Approval is not guaranteed" in packages["market_seo"].body


def test_owned_web_package_requires_street_address():
    property_ = OwnerFinanceProperty(city="Decatur", state="IL", monthly_payment=Decimal("995"))
    with pytest.raises(OwnedWebPackageError, match="street address"):
        build_owned_web_package(
            property_,
            channel_key="property_page",
            channel_name="Property Landing Page",
            tracked_link="https://example.com/track",
        )


def test_owned_web_package_rejects_unsupported_channel():
    with pytest.raises(OwnedWebPackageError, match="Unsupported"):
        build_owned_web_package(
            sample_property(),
            channel_key="unknown",
            channel_name="Unknown",
            tracked_link="https://example.com/track",
        )
