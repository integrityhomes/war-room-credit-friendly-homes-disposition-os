from datetime import UTC, datetime

import pytest

from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.social_publish_handoff import (
    SocialPublishHandoffError,
    SocialPublishSettings,
    build_social_publish_payload,
    dispatch_social_publish_handoff,
)
from cfh_disposition.social_video_channels import build_social_video_package


def _property():
    return OwnerFinanceProperty(
        address="100 Main St",
        city="Decatur",
        state="IL",
        zip_code="62521",
        total_price=100000,
        down_payment=5000,
        monthly_payment=1200,
    )


def _package(channel_key="instagram"):
    names = {
        "instagram": "Instagram Reels & Posts",
        "tiktok": "TikTok",
        "youtube": "YouTube Shorts",
    }
    return build_social_video_package(
        _property(),
        channel_key=channel_key,
        channel_name=names[channel_key],
        tracked_link=f"https://example.com/{channel_key}",
    )


def test_social_publish_settings_require_https():
    assert SocialPublishSettings.from_mapping({}).configured is False
    assert SocialPublishSettings.from_mapping(
        {"SOCIAL_PUBLISH_WEBHOOK_URL": "http://example.com/hook"}
    ).configured is False
    assert SocialPublishSettings.from_mapping(
        {"SOCIAL_PUBLISH_WEBHOOK_URL": "https://example.com/hook"}
    ).configured is True


@pytest.mark.parametrize("channel_key", ["instagram", "tiktok", "youtube"])
def test_publish_payload_supports_all_three_social_channels(channel_key):
    package = _package(channel_key)
    now = datetime(2026, 8, 29, 20, 45, tzinfo=UTC)
    payload = build_social_publish_payload(
        property_record=_property(),
        package=package,
        campaign="social_decatur_il",
        caption=package.caption_variants[0],
        approved_by="Sabrina",
        now=now,
    )

    assert payload["channel"] == channel_key
    assert payload["approved_by"] == "Sabrina"
    assert payload["approved_at"] == now.isoformat()
    assert payload["marketing"]["caption"] == package.caption_variants[0]
    assert payload["marketing"]["tracked_dwelyx_link"] == package.tracked_link
    assert payload["publication"]["cfh_handoff_is_not_proof_of_publication"] is True
    assert payload["compliance"]["do_not_change_title_or_caption"] is True


def test_publish_payload_rejects_modified_caption_and_missing_approver():
    package = _package()
    with pytest.raises(SocialPublishHandoffError, match="fact-locked"):
        build_social_publish_payload(
            property_record=_property(),
            package=package,
            campaign="social_decatur_il",
            caption="Edited unapproved caption",
            approved_by="Sabrina",
        )
    with pytest.raises(SocialPublishHandoffError, match="approving operator"):
        build_social_publish_payload(
            property_record=_property(),
            package=package,
            campaign="social_decatur_il",
            caption=package.caption_variants[0],
            approved_by="",
        )


def test_social_publish_idempotency_key_is_stable_for_same_approved_package():
    package = _package()
    kwargs = {
        "property_record": _property(),
        "package": package,
        "campaign": "social_decatur_il",
        "caption": package.caption_variants[0],
        "approved_by": "Sabrina",
    }
    first = build_social_publish_payload(**kwargs)
    second = build_social_publish_payload(**kwargs)
    changed = build_social_publish_payload(
        **{**kwargs, "caption": package.caption_variants[1]}
    )

    assert first["idempotency_key"] == second["idempotency_key"]
    assert first["idempotency_key"] != changed["idempotency_key"]


def test_dispatch_fails_closed_without_social_adapter():
    package = _package()
    with pytest.raises(SocialPublishHandoffError, match="Social publication is not connected"):
        dispatch_social_publish_handoff(
            {},
            property_record=_property(),
            package=package,
            campaign="social_decatur_il",
            caption=package.caption_variants[0],
            approved_by="Sabrina",
        )
