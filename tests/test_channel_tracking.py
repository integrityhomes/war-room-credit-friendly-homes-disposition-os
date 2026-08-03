from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from cfh_disposition.analytics import ClickEvent
from cfh_disposition.channel_tracking import (
    build_channel_links,
    canonical_channel_key,
    channel_scorecard,
    unmapped_clicks,
)
from cfh_disposition.channels import CHANNELS


def event(medium: str, *, campaign: str = "summer", property_id: str | None = None) -> ClickEvent:
    return ClickEvent(
        occurred_at=datetime(2026, 8, 3, 18, 0, tzinfo=UTC),
        source="credit_friendly_homes",
        medium=medium,
        campaign=campaign,
        property_id=property_id,
    )


def test_build_channel_links_creates_one_unique_link_for_every_channel():
    property_id = uuid4()
    rows = build_channel_links(
        "https://www.dwelyx.com",
        campaign="August Bristol Homes",
        property_id=property_id,
        tracking_base_url="https://tracking.example.com",
    )

    assert len(rows) == len(CHANNELS) == 14
    assert [row["Channel key"] for row in rows] == [channel.key for channel in CHANNELS]
    assert len({row["Tracked Dwelyx link"] for row in rows}) == 14

    for channel, row in zip(CHANNELS, rows, strict=True):
        parts = urlsplit(row["Tracked Dwelyx link"])
        query = parse_qs(parts.query)
        assert parts.netloc == "tracking.example.com"
        assert query["medium"] == [channel.key]
        assert query["campaign"] == ["august_bristol_homes"]
        assert query["property_id"] == [str(property_id)]


def test_scorecard_always_contains_all_14_channels_and_zero_rows():
    property_id = "property-123"
    rows = channel_scorecard(
        [
            event("marketplace", property_id=property_id),
            event("facebook_marketplace", property_id=property_id),
            event("email", campaign="follow_up"),
        ]
    )

    assert len(rows) == 14
    by_key = {row.channel.key: row for row in rows}
    assert by_key["marketplace"].clicks == 2
    assert by_key["marketplace"].campaigns == 1
    assert by_key["marketplace"].properties == 1
    assert by_key["email"].clicks == 1
    assert by_key["tiktok"].clicks == 0
    assert by_key["marketplace"].traffic_share == 2 / 3 * 100


def test_legacy_medium_aliases_roll_into_the_correct_channel():
    assert canonical_channel_key("property_landing_page") == "property_page"
    assert canonical_channel_key("Facebook Marketplace") == "marketplace"
    assert canonical_channel_key("google") == "google_ads"
    assert canonical_channel_key("youtube_shorts") == "youtube"


def test_unmapped_clicks_are_separated_from_the_14_channel_scorecard():
    unknown = event("executive_war_room")
    mapped = event("sms")
    assert unmapped_clicks([unknown, mapped]) == [unknown]
