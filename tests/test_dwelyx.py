from uuid import uuid4

from cfh_disposition.dwelyx import DEFAULT_DWELYX_URL, build_dwelyx_url, dwelyx_base_url


def test_dwelyx_base_url_defaults_and_normalizes():
    assert dwelyx_base_url() == DEFAULT_DWELYX_URL
    assert dwelyx_base_url({"DWELYX_URL": "www.dwelyx.com/"}) == "https://www.dwelyx.com"


def test_build_dwelyx_url_adds_attribution():
    property_id = uuid4()
    url = build_dwelyx_url(
        "https://www.dwelyx.com",
        source="Credit Friendly Homes",
        medium="Facebook Marketplace",
        campaign="Owner Finance Homes",
        property_id=property_id,
    )
    assert url.startswith("https://www.dwelyx.com?")
    assert "utm_source=credit_friendly_homes" in url
    assert "utm_medium=facebook_marketplace" in url
    assert "utm_campaign=owner_finance_homes" in url
    assert f"utm_content=property_{property_id}" in url


def test_build_dwelyx_url_preserves_existing_query_values():
    url = build_dwelyx_url(
        "https://www.dwelyx.com/homes?state=VA",
        source="credit_friendly_homes",
        medium="signs",
    )
    assert "state=VA" in url
    assert "utm_medium=signs" in url
