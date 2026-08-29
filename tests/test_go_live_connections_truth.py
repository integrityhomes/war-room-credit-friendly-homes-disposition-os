from cfh_disposition.go_live_connections import build_connection_status, connection_summary


def _rows(values):
    return {row.key: row for row in build_connection_status(values)}


def test_unused_provider_api_keys_do_not_fake_email_or_sms_handoff_connection():
    rows = _rows(
        {
            "EMAIL_PROVIDER_API_KEY": "not-used-by-cfh-handoff",
            "SMS_PROVIDER_API_KEY": "not-used-by-cfh-handoff",
        }
    )

    assert rows["email_sender"].configured is False
    assert rows["sms_sender"].configured is False
    assert rows["email_sender"].status_label == "Needs connection"
    assert rows["sms_sender"].status_label == "Needs connection"


def test_actual_https_handoff_settings_are_reported_as_configured():
    rows = _rows(
        {
            "EMAIL_SENDER_WEBHOOK_URL": "https://example.com/email",
            "SMS_SENDER_WEBHOOK_URL": "https://example.com/sms",
            "BUYER_OUTREACH_WEBHOOK_URL": "https://example.com/reactivation",
            "SOCIAL_PUBLISH_WEBHOOK_URL": "https://example.com/social",
        }
    )

    assert rows["email_sender"].configured is True
    assert rows["sms_sender"].configured is True
    assert rows["buyer_reactivation"].configured is True
    assert rows["social_publish"].configured is True


def test_blog_and_market_seo_are_not_listed_as_general_webhook_dependencies():
    rows = _rows({})
    required_for = rows["publishing_webhook"].required_for

    assert "Blog" in required_for
    assert "no longer depend" in required_for
    assert "Market SEO" in required_for


def test_meta_and_google_presence_is_not_labeled_as_launch_authority():
    rows = _rows(
        {
            "META_AD_ACCOUNT_ID": "123",
            "GOOGLE_ADS_CUSTOMER_ID": "456",
        }
    )

    assert rows["meta_ads"].configured is True
    assert rows["google_ads"].configured is True
    assert rows["meta_ads"].status_label == "Account details present"
    assert rows["google_ads"].status_label == "Account details present"
    assert "not launch authority" in rows["meta_ads"].next_step.lower()
    assert "not launch authority" in rows["google_ads"].next_step.lower()


def test_connection_summary_uses_configured_not_connected_language():
    rows = build_connection_status(
        {"EMAIL_SENDER_WEBHOOK_URL": "https://example.com/email"}
    )
    summary = connection_summary(rows)

    assert summary["total"] == 7
    assert summary["configured"] == 1
    assert summary["remaining"] == 6
    assert "connected" not in summary
