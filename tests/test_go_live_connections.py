from cfh_disposition.go_live_connections import build_connection_status, connection_summary


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
