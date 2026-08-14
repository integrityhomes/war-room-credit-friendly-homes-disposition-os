from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.outreach_channels import OutreachPackageError, build_outreach_package


def property_record() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        down_payment=Decimal("3500"),
        monthly_payment=Decimal("995"),
    )


def test_outreach_channels_keep_distinct_attribution():
    property_ = property_record()
    rows = build_channel_links(
        "https://www.dwelyx.com/buyer/register",
        campaign="decatur_outreach",
        property_id=property_.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    by_key = {row["Channel key"]: row["Tracked Dwelyx link"] for row in rows}

    urls = [by_key[key] for key in ("email", "sms", "reactivation")]
    assert len(set(urls)) == 3
    for key, url in zip(("email", "sms", "reactivation"), urls, strict=True):
        query = parse_qs(urlsplit(url).query)
        assert query["medium"] == [key]
        assert query["campaign"] == ["decatur_outreach"]
        assert query["property_id"] == [str(property_.property_id)]


@pytest.mark.parametrize("channel_key", ["email", "sms", "reactivation"])
def test_outreach_package_uses_verified_property_facts(channel_key):
    property_ = property_record()
    link = f"https://tracking.example.com/?medium={channel_key}"
    package = build_outreach_package(
        property_,
        channel_key=channel_key,
        channel_name=channel_key,
        tracked_link=link,
    )

    assert len(package.message_variants) == 3
    assert package.tracked_link == link
    for message in package.message_variants:
        assert "945 W Packard St" in message
        assert "$995" in message
        assert "$3,500" in message
        assert link in message


def test_outreach_package_requires_street_address():
    property_ = OwnerFinanceProperty(city="Decatur", state="IL", monthly_payment=Decimal("995"))
    with pytest.raises(OutreachPackageError, match="address"):
        build_outreach_package(
            property_,
            channel_key="email",
            channel_name="Matched Buyer Email",
            tracked_link="https://tracking.example.com/?medium=email",
        )


def test_outreach_package_blocks_unsupported_channel():
    with pytest.raises(OutreachPackageError, match="Unsupported"):
        build_outreach_package(
            property_record(),
            channel_key="unknown",
            channel_name="Unknown",
            tracked_link="https://tracking.example.com/?medium=unknown",
        )
