from datetime import UTC, datetime
from decimal import Decimal

import cfh_disposition.safe_payload_test as safe_payload_test
from cfh_disposition.ai_campaign import build_fallback_campaign
from cfh_disposition.automatic_launch import build_automatic_launch_payload
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS
from cfh_disposition.dwelyx import DEFAULT_DWELYX_URL
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.safe_payload_test import (
    SAFE_FULL_PAYLOAD_TEST_EVENT,
    build_safe_full_payload_test_payload,
)


def sample_full_payload():
    item = OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("94500"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        condition_summary="Livable property.",
        repairs_needed="Buyer to verify.",
        showing_instructions="Appointment required.",
        public_disclosures="Terms subject to verification.",
        photo_urls=["https://example.com/front.jpg"],
    )
    links = build_channel_links(
        DEFAULT_DWELYX_URL,
        campaign="owner_finance_homes",
        property_id=item.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    links_by_key = {row["Channel key"]: row for row in links}
    package = build_fallback_campaign(
        item,
        links_by_key["property_page"]["Tracked Dwelyx link"],
    )
    return build_automatic_launch_payload(
        item,
        package,
        links_by_key,
        campaign="owner_finance_homes",
        approved_by="Shawn",
        approved_at=datetime(2026, 8, 26, 20, 0, tzinfo=UTC),
    )


def test_safe_full_payload_keeps_complete_campaign_but_zero_executable_channels() -> None:
    full_payload = sample_full_payload()
    safe = build_safe_full_payload_test_payload(
        full_payload,
        requested_by="Shawn",
        requested_at=datetime(2026, 8, 26, 20, 5, tzinfo=UTC),
    )

    assert safe["event"] == SAFE_FULL_PAYLOAD_TEST_EVENT
    assert safe["test_mode"] is True
    assert safe["execution_allowed"] is False
    assert safe["external_actions_allowed"] is False
    assert safe["send_email"] is False
    assert safe["send_sms"] is False
    assert safe["publish_social"] is False
    assert safe["publish_ads"] is False
    assert safe["spend_money"] is False
    assert safe["channels"] == []
    assert len(safe["full_campaign_payload"]["channels"]) == len(CHANNELS) == 15
    assert safe["full_campaign_payload"]["property"]["address"] == "945 W Packard St"
    assert safe["safety"]["top_level_channel_count"] == 0
    assert safe["safety"]["full_payload_channel_count"] == 15


def test_dispatch_refuses_payload_with_executable_top_level_channels() -> None:
    full_payload = sample_full_payload()
    unsafe = build_safe_full_payload_test_payload(full_payload, requested_by="Shawn")
    unsafe["channels"] = [{"channel_key": "email"}]

    settings = safe_payload_test.AutomationDispatchSettings(
        webhook_url="https://hooks.zapier.com/hooks/catch/example/test/"
    )

    try:
        safe_payload_test.dispatch_safe_full_payload_test(unsafe, settings)
    except ValueError as exc:
        assert "executable top-level channels" in str(exc)
    else:
        raise AssertionError("Unsafe full-payload test should have been rejected before network access")
