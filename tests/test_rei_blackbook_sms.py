from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty, PropertyStatus
from cfh_disposition.rei_blackbook_sms import (
    ReiBlackBookSmsError,
    SmsHandoffSettings,
    build_sms_handoff_payload,
    ensure_buyer_can_receive_sms,
)


def _buyer(**updates) -> BuyerProfile:
    values = {
        "first_name": "Test",
        "last_name": "Buyer",
        "phone": "7575551212",
        "sms_consent": True,
        "do_not_contact": False,
    }
    values.update(updates)
    return BuyerProfile(**values)


def _property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        status=PropertyStatus.LIVE,
        address="123 Main St",
        city="Franklin",
        state="VA",
        zip_code="23851",
        bedrooms=3,
        bathrooms=Decimal("2"),
        total_price=Decimal("85000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1100"),
    )


def test_sms_handoff_requires_real_https_webhook():
    assert not SmsHandoffSettings.from_mapping({}).configured
    assert not SmsHandoffSettings.from_mapping({"SMS_SENDER_WEBHOOK_URL": "http://example.com"}).configured
    assert SmsHandoffSettings.from_mapping({"SMS_SENDER_WEBHOOK_URL": "https://hooks.zapier.com/hooks/catch/example"}).configured


def test_sms_handoff_blocks_missing_consent():
    with pytest.raises(ReiBlackBookSmsError, match="consent"):
        ensure_buyer_can_receive_sms(_buyer(sms_consent=False))


def test_sms_handoff_blocks_do_not_contact():
    with pytest.raises(ReiBlackBookSmsError, match="Do Not Contact"):
        ensure_buyer_can_receive_sms(_buyer(do_not_contact=True))


def test_payload_preserves_marketing_attribution_and_sender_boundary():
    buyer = _buyer()
    property_record = _property()
    payload = build_sms_handoff_payload(
        buyer=buyer,
        property_record=property_record,
        campaign="va_owner_finance_august",
        message="Owner financing opportunity. See details: https://example.test/t/abc",
        tracked_link="https://example.test/t/abc",
        requested_by="Sabrina",
        now=datetime(2026, 8, 22, 23, 0, tzinfo=UTC),
    )

    assert payload["sender_system"] == "rei_blackbook_profit_dial"
    assert payload["action"] == "create_or_update_contact_and_run_sms_workflow"
    assert payload["buyer"]["phone"] == buyer.phone
    assert payload["marketing"]["property_id"] == str(property_record.property_id)
    assert payload["marketing"]["property_address"] == property_record.display_address
    assert payload["marketing"]["campaign"] == "va_owner_finance_august"
    assert payload["marketing"]["source"] == "credit_friendly_homes"
    assert payload["marketing"]["channel"] == "sms"
    assert payload["marketing"]["tracked_dwelyx_link"] == "https://example.test/t/abc"
    assert payload["instructions"]["do_not_change_message"] is True
