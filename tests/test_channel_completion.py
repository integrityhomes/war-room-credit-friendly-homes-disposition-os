from cfh_disposition.channel_completion import build_channel_completion, completion_summary
from cfh_disposition.channels import ALL_MARKETING_CHANNELS


def test_completion_audit_covers_every_registered_channel_once():
    rows = build_channel_completion()
    assert len(rows) == len(ALL_MARKETING_CHANNELS) == 16
    assert len({row.key for row in rows}) == 16
    assert {row.key for row in rows} == {channel.key for channel in ALL_MARKETING_CHANNELS}


def test_every_current_channel_is_built_and_tracked_but_readiness_is_honest():
    rows = build_channel_completion()
    assert all(row.built for row in rows)
    assert all(row.tracked for row in rows)
    assert not all(row.ready_to_use for row in rows)


def test_ready_now_is_reserved_for_internal_or_complete_assisted_workflows():
    rows = {row.key: row for row in build_channel_completion()}
    assert rows["property_page"].ready_to_use is True
    for key in ("marketplace", "facebook_groups", "classifieds", "nextdoor"):
        assert rows[key].ready_to_use is True
        assert rows[key].manual_final_step_required is True
    for key in (
        "blog",
        "market_seo",
        "email",
        "sms",
        "reactivation",
        "meta_ads",
        "google_ads",
        "instagram",
        "tiktok",
        "youtube",
        "chatgpt_ads",
    ):
        assert rows[key].ready_to_use is False
        assert rows[key].connection_required is True


def test_audit_distinguishes_manual_paid_and_connected_work():
    rows = {row.key: row for row in build_channel_completion()}
    assert "Manual final post" in rows["marketplace"].next_requirement
    assert "Meta" in rows["meta_ads"].next_requirement
    assert "email sender" in rows["email"].next_requirement
    assert "SMS" in rows["sms"].next_requirement
    assert "OpenAI Ads Manager" in rows["chatgpt_ads"].next_requirement
    assert rows["property_page"].next_requirement == "Ready now"


def test_completion_summary_matches_rows():
    summary = completion_summary(build_channel_completion())
    assert summary["total"] == 16
    assert summary["built"] == 16
    assert summary["tracked"] == 16
    assert summary["ready_to_use"] == 5
    assert summary["connection_required"] == 11
    assert summary["manual_final_step_required"] == 7
    assert summary["not_ready_now"] == 11
