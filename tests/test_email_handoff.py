from datetime import UTC, datetime

import pytest

from cfh_disposition.email_handoff import (
    EmailHandoffError,
    EmailHandoffSettings,
    build_email_handoff_payload,
    dispatch_email_handoff,
    ensure_buyer_can_receive_email,
)
from cfh_disposition.models import BuyerProfile, OwnerFinanceProperty


def _buyer(**overrides):
    values = {
        "first_name": "Avery",
        "last_name": "Buyer",
        "email": "avery@example.com",
        "email_consent": True,
        "do_not_contact": False,
    }
    values.update(overrides)
    return BuyerProfile(**values)


def _property():
    return OwnerFinanceProperty(
        address="100 Main St",
        city="Decatur",
        state="IL",
        zip_code="62521",
    )


def test_email_settings_require_https_webhook():
    assert EmailHandoffSettings.from_mapping({}).configured is False
    assert EmailHandoffSettings.from_mapping(
        {"EMAIL_SENDER_WEBHOOK_URL": "http://example.com/hook"}
    ).configured is False
    assert EmailHandoffSettings.from_mapping(
        {"EMAIL_SENDER_WEBHOOK_URL": "https://example.com/hook"}
    ).configured is True


def test_email_handoff_blocks_missing_consent_and_do_not_contact():
    with pytest.raises(EmailHandoffError, match="saved email consent"):
        ensure_buyer_can_receive_email(_buyer(email_consent=False))
    with pytest.raises(EmailHandoffError, match="Do Not Contact"):
        ensure_buyer_can_receive_email(_buyer(do_not_contact=True))
    with pytest.raises(EmailHandoffError, match="saved email address"):
        ensure_buyer_can_receive_email(_buyer(email=""))


def test_email_payload_preserves_locked_content_and_compliance_flags():
    now = datetime(2026, 8, 29, 20, 30, tzinfo=UTC)
    payload = build_email_handoff_payload(
        buyer=_buyer(),
        property_record=_property(),
        campaign="buyer_outreach_decatur_il",
        subject="Current owner-finance home in Decatur",
        message="Here are the verified details. View them at the tracked link.",
        tracked_link="https://example.com/dwelyx-track",
        requested_by="Sabrina",
        now=now,
    )

    assert payload["channel"] == "email"
    assert payload["recipient"]["email"] == "avery@example.com"
    assert payload["recipient"]["email_consent_verified"] is True
    assert payload["marketing"]["subject"] == "Current owner-finance home in Decatur"
    assert payload["marketing"]["message"] == (
        "Here are the verified details. View them at the tracked link."
    )
    assert payload["marketing"]["tracked_dwelyx_link"] == "https://example.com/dwelyx-track"
    assert payload["compliance"]["do_not_change_subject_or_message"] is True
    assert payload["compliance"]["unsubscribe_handling_required_downstream"] is True
    assert payload["requested_at"] == now.isoformat()


def test_email_idempotency_key_is_stable_for_same_locked_message():
    kwargs = {
        "buyer": _buyer(),
        "property_record": _property(),
        "campaign": "buyer_outreach_decatur_il",
        "subject": "Subject",
        "message": "Locked body",
        "tracked_link": "https://example.com/track",
        "requested_by": "Sabrina",
    }
    first = build_email_handoff_payload(**kwargs)
    second = build_email_handoff_payload(**kwargs)
    changed = build_email_handoff_payload(**{**kwargs, "message": "Different locked body"})

    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["idempotency_key"] != changed["idempotency_key"]


def test_dispatch_fails_closed_without_configured_sender():
    with pytest.raises(EmailHandoffError, match="Email sender is not connected"):
        dispatch_email_handoff(
            {},
            buyer=_buyer(),
            property_record=_property(),
            campaign="buyer_outreach_decatur_il",
            subject="Subject",
            message="Locked body",
            tracked_link="https://example.com/track",
            requested_by="Sabrina",
        )
