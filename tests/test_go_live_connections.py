from datetime import UTC, datetime

from cfh_disposition.go_live_connections import (
    CONNECTION_TEST_EVENT,
    automation_connection_sample_json,
    build_connection_status,
    build_publishing_connection_test_payload,
    connection_summary,
)


def test_go_live_connections_report_all_categories():
    rows = build_connection_status({})
    assert {row.key for row in rows} == {
        "publishing_webhook",
        "email_sender",
        "sms_sender",
        "meta_ads",
        "google_ads",
    }
    assert all(not row.configured for row in rows)
    assert connection_summary(rows) == {"total": 5, "connected": 0, "remaining": 5}


def test_existing_automation_alias_counts_as_connected():
    rows = build_connection_status({"MAKE_WEBHOOK_URL": "https://example.com/hooks/cfh"})
    by_key = {row.key: row for row in rows}
    assert by_key["publishing_webhook"].configured is True


def test_provider_connections_are_detected_without_exposing_values():
    secrets = {
        "EMAIL_PROVIDER_API_KEY": "email-secret",
        "SMS_SENDER_WEBHOOK_URL": "https://example.com/sms",
        "META_AD_ACCOUNT_ID": "123456789",
        "GOOGLE_ADS_CUSTOMER_ID": "123-456-7890",
    }
    rows = build_connection_status(secrets)
    by_key = {row.key: row for row in rows}
    assert by_key["email_sender"].configured is True
    assert by_key["sms_sender"].configured is True
    assert by_key["meta_ads"].configured is True
    assert by_key["google_ads"].configured is True
    rendered = " ".join(row.next_step for row in rows)
    for secret_value in secrets.values():
        assert secret_value not in rendered


def test_safe_publishing_connection_payload_cannot_publish_anything():
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    payload = build_publishing_connection_test_payload(requested_by="Shawn", now=now)
    assert payload["event"] == CONNECTION_TEST_EVENT
    assert payload["test_only"] is True
    assert payload["requested_by"] == "Shawn"
    assert payload["sent_at"] == "2026-08-18T12:00:00+00:00"
    serialized = str(payload).lower()
    assert "property_id" not in serialized
    assert "buyer_id" not in serialized
    assert "daily_budget" not in serialized
    assert "test only" in payload["instructions"].lower()


def test_automation_sample_json_is_safe_and_exposes_no_secret():
    sample = automation_connection_sample_json(requested_by="Connection Center")
    assert CONNECTION_TEST_EVENT in sample
    assert '"test_only": true' in sample
    assert "webhook" not in sample.lower()
    assert "secret" not in sample.lower()
