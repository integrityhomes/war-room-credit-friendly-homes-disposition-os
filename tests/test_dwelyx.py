from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from cfh_disposition.dwelyx import (
    DEFAULT_DWELYX_URL,
    DEFAULT_TRACKING_APP_URL,
    build_direct_dwelyx_url,
    build_dwelyx_url,
    dwelyx_base_url,
    tracking_app_base_url,
)


def test_dwelyx_base_url_defaults_to_buyer_registration_and_normalizes():
    assert dwelyx_base_url() == "https://www.dwelyx.com/buyer/register"
    assert dwelyx_base_url() == DEFAULT_DWELYX_URL
    assert (
        dwelyx_base_url({"DWELYX_BUYER_URL": "www.dwelyx.com/buyer/register/"})
        == "https://www.dwelyx.com/buyer/register"
    )
    assert tracking_app_base_url() == DEFAULT_TRACKING_APP_URL


def test_legacy_dwelyx_homepage_setting_does_not_override_buyer_destination():
    assert (
        dwelyx_base_url({"DWELYX_URL": "https://www.dwelyx.com"})
        == "https://www.dwelyx.com/buyer/register"
    )


def test_build_direct_dwelyx_url_adds_attribution():
    property_id = uuid4()
    url = build_direct_dwelyx_url(
        "https://www.dwelyx.com/buyer/register",
        source="Credit Friendly Homes",
        medium="Facebook Marketplace",
        campaign="Owner Finance Homes",
        property_id=property_id,
    )
    assert url.startswith("https://www.dwelyx.com/buyer/register?")
    assert "utm_source=credit_friendly_homes" in url
    assert "utm_medium=facebook_marketplace" in url
    assert "utm_campaign=owner_finance_homes" in url
    assert f"utm_content=property_{property_id}" in url


def test_build_dwelyx_url_uses_tracking_redirect():
    property_id = uuid4()
    url = build_dwelyx_url(
        "https://www.dwelyx.com/buyer/register",
        source="Credit Friendly Homes",
        medium="Facebook Marketplace",
        campaign="Owner Finance Homes",
        property_id=property_id,
    )
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}" == DEFAULT_TRACKING_APP_URL
    assert query["go"] == ["dwelyx"]
    assert query["target"] == ["https://www.dwelyx.com/buyer/register"]
    assert query["source"] == ["credit_friendly_homes"]
    assert query["medium"] == ["facebook_marketplace"]
    assert query["campaign"] == ["owner_finance_homes"]
    assert query["property_id"] == [str(property_id)]


def test_direct_dwelyx_url_preserves_existing_query_values():
    url = build_direct_dwelyx_url(
        "https://www.dwelyx.com/buyer/register?ref=cfh",
        source="credit_friendly_homes",
        medium="signs",
    )
    assert "ref=cfh" in url
    assert "utm_medium=signs" in url
