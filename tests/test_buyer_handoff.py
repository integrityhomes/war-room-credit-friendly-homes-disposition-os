from datetime import UTC, datetime
from decimal import Decimal

from cfh_disposition.ai_campaign import build_fallback_campaign
from cfh_disposition.automatic_launch import build_automatic_launch_payload, expected_automatic_channel_keys
from cfh_disposition.buyer_handoff import (
    BUYER_REACTIVATION_BLOCK_REASON,
    enrich_launch_payload_with_buyer_audience,
)
from cfh_disposition.buyer_intent import BuyerIntentLedger, build_match
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.dwelyx import DEFAULT_DWELYX_URL
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty


def _fixture():
    property_record = OwnerFinanceProperty(
        address="101 Test Street",
        city="Bristol",
        state="VA",
        zip_code="24201",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("100000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
        condition_summary="As-is home.",
        showing_instructions="Appointment required.",
        public_disclosures="Terms subject to verification.",
        photo_urls=["https://example.com/front.jpg"],
    )
    buyer = BuyerProfile(
        first_name="Taylor",
        email="taylor@example.com",
        phone="+17575550101",
        preferred_cities=["Bristol"],
        preferred_states=["VA"],
        minimum_bedrooms=2,
        maximum_monthly_payment=Decimal("1400"),
        available_down_payment=Decimal("6000"),
        email_consent=True,
        sms_consent=True,
    )
    ledger = BuyerIntentLedger(updated_at=datetime(2026, 8, 27, tzinfo=UTC))
    match = build_match(buyer, property_record, ledger, DEFAULT_DWELYX_URL)
    links = build_channel_links(
        DEFAULT_DWELYX_URL,
        campaign="owner_finance_homes",
        property_id=property_record.property_id,
        tracking_base_url="https://tracking.example.com",
    )
    links_by_key = {row["Channel key"]: row for row in links}
    package = build_fallback_campaign(
        property_record,
        links_by_key["property_page"]["Tracked Dwelyx link"],
    )
    payload = build_automatic_launch_payload(
        property_record,
        package,
        links_by_key,
        campaign="owner_finance_homes",
        approved_by="Sabrina",
    )
    return payload, match


def test_consent_ready_buyer_is_attached_to_email_and_sms() -> None:
    payload, match = _fixture()
    enriched = enrich_launch_payload_with_buyer_audience(payload, [match])
    rows = {row["channel_key"]: row for row in enriched["channels"]}

    assert enriched["buyer_audience"]["email_recipient_count"] == 1
    assert enriched["buyer_audience"]["sms_recipient_count"] == 1
    assert enriched["buyer_audience"]["email_recipient_addresses"] == ["taylor@example.com"]
    assert enriched["buyer_audience"]["sms_recipient_phone_numbers"] == ["+17575550101"]
    assert rows["email"]["recipients"][0]["recipient"] == "taylor@example.com"
    assert rows["email"]["recipients"][0]["email"] == "taylor@example.com"
    assert rows["sms"]["recipients"][0]["recipient"] == "+17575550101"
    assert rows["sms"]["recipients"][0]["phone"] == "+17575550101"
    assert rows["email"]["recipient_addresses"] == ["taylor@example.com"]
    assert rows["sms"]["recipient_phone_numbers"] == ["+17575550101"]
    assert rows["email"]["posting_blocked"] is False
    assert rows["sms"]["posting_blocked"] is False


def test_reactivation_is_never_duplicated_by_property_launch() -> None:
    payload, match = _fixture()
    enriched = enrich_launch_payload_with_buyer_audience(payload, [match])
    rows = {row["channel_key"]: row for row in enriched["channels"]}

    assert rows["reactivation"]["posting_blocked"] is True
    assert rows["reactivation"]["recipients"] == []
    assert rows["reactivation"]["block_reason"] == BUYER_REACTIVATION_BLOCK_REASON
    assert "reactivation" not in expected_automatic_channel_keys(enriched)


def test_no_consent_ready_audience_blocks_email_and_sms() -> None:
    payload, _match = _fixture()
    enriched = enrich_launch_payload_with_buyer_audience(payload, [])
    rows = {row["channel_key"]: row for row in enriched["channels"]}

    assert enriched["buyer_audience"]["email_recipient_addresses"] == []
    assert enriched["buyer_audience"]["sms_recipient_phone_numbers"] == []
    assert rows["email"]["posting_blocked"] is True
    assert rows["sms"]["posting_blocked"] is True
    assert rows["email"]["recipients"] == []
    assert rows["sms"]["recipients"] == []
    assert rows["email"]["recipient_addresses"] == []
    assert rows["sms"]["recipient_phone_numbers"] == []
    assert "email" not in expected_automatic_channel_keys(enriched)
    assert "sms" not in expected_automatic_channel_keys(enriched)
