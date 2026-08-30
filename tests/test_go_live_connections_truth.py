from cfh_disposition.go_live_connections import build_connection_status, connection_summary


def test_connection_status_uses_configuration_truth_not_live_delivery_language():
    rows = {row.key: row for row in build_connection_status({})}

    assert rows["publishing_webhook"].status_label == "Needs connection"
    assert rows["email_sender"].status_label == "Needs connection"
    assert rows["sms_sender"].status_label == "Needs connection"
    assert rows["buyer_reactivation"].status_label == "Needs connection"
    assert rows["social_publish"].status_label == "Optional / manual final post"
    assert rows["agent_finder"].status_label == "Needs connection"
    assert rows["meta_ads"].status_label == "Needs account setup"
    assert rows["google_ads"].status_label == "Needs account setup"


def test_configured_handoffs_still_keep_consent_and_execution_boundaries_visible():
    rows = {
        row.key: row
        for row in build_connection_status(
            {
                "EMAIL_SENDER_WEBHOOK_URL": "https://example.com/email",
                "SMS_SENDER_WEBHOOK_URL": "https://example.com/sms",
                "BUYER_OUTREACH_WEBHOOK_URL": "https://example.com/outreach",
                "SOCIAL_PUBLISH_WEBHOOK_URL": "https://example.com/social",
                "SEARCHAPI_API_KEY": "configured-search-key",
            }
        )
    }

    assert rows["email_sender"].configured is True
    assert rows["sms_sender"].configured is True
    assert rows["buyer_reactivation"].configured is True
    assert rows["social_publish"].configured is True
    assert rows["agent_finder"].configured is True
    assert "consent" in rows["email_sender"].next_step.lower()
    assert "consent" in rows["sms_sender"].next_step.lower()
    assert "consent" in rows["buyer_reactivation"].next_step.lower()
    assert "not proof" in rows["social_publish"].next_step.lower()
    assert "verification before outreach" in rows["agent_finder"].next_step.lower()


def test_paid_account_details_do_not_claim_launch_authority():
    rows = {
        row.key: row
        for row in build_connection_status(
            {
                "META_AD_ACCOUNT_ID": "123",
                "GOOGLE_ADS_CUSTOMER_ID": "456",
            }
        )
    }

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

    assert summary["total"] == 8
    assert summary["configured"] == 1
    assert summary["remaining"] == 7
    assert "connected" not in summary
