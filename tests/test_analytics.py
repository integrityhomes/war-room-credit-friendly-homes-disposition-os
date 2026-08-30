from datetime import UTC, datetime

from cfh_disposition.analytics import (
    LIVE_TRAFFIC,
    TEST_TRAFFIC,
    UNCLASSIFIED_TRAFFIC,
    ClickEvent,
    click_summary,
    decode_event_token,
    encode_event_token,
    event_from_object_name,
    event_object_path,
    live_click_events,
    traffic_type_counts,
)


def sample_event(*, traffic_type: str = UNCLASSIFIED_TRAFFIC) -> ClickEvent:
    return ClickEvent(
        occurred_at=datetime(2026, 8, 3, 22, 30, tzinfo=UTC),
        source="credit_friendly_homes",
        medium="facebook_marketplace",
        campaign="owner_finance_homes",
        property_id="123-property",
        traffic_type=traffic_type,
    )


def test_event_token_round_trip():
    event = sample_event(traffic_type=LIVE_TRAFFIC)
    restored = decode_event_token(encode_event_token(event))
    assert restored == event
    assert restored.is_live


def test_legacy_event_without_traffic_type_is_unclassified():
    event = sample_event()
    payload = event.to_payload()
    payload.pop("traffic_type")
    legacy = ClickEvent.from_payload(payload)
    assert legacy.traffic_type == UNCLASSIFIED_TRAFFIC
    assert not legacy.is_live
    assert not legacy.is_test


def test_event_object_path_contains_date_and_decodes():
    event = sample_event(traffic_type=TEST_TRAFFIC)
    path = event_object_path(event)
    assert path.startswith("clicks/2026/08/03/")
    assert event_from_object_name(path) == event
    assert event_from_object_name(path).is_test


def test_click_summary_groups_channels_campaigns_and_properties():
    event = sample_event(traffic_type=LIVE_TRAFFIC)
    second = ClickEvent(
        occurred_at=event.occurred_at,
        source=event.source,
        medium="email",
        campaign=event.campaign,
        property_id=None,
        traffic_type=LIVE_TRAFFIC,
    )
    summary = click_summary([event, event, second])
    assert summary["total"] == 3
    assert summary["sources"] == {"facebook_marketplace": 2, "email": 1}
    assert summary["campaigns"] == {"owner_finance_homes": 3}
    assert summary["properties"] == {"123-property": 2}


def test_live_click_filter_excludes_tests_and_legacy_events():
    live = sample_event(traffic_type=LIVE_TRAFFIC)
    test = sample_event(traffic_type=TEST_TRAFFIC)
    legacy = sample_event()

    assert live_click_events([live, test, legacy]) == [live]
    assert traffic_type_counts([live, test, legacy, test]) == {
        LIVE_TRAFFIC: 1,
        TEST_TRAFFIC: 2,
        UNCLASSIFIED_TRAFFIC: 1,
    }


def test_invalid_object_name_is_ignored():
    assert event_from_object_name("not-an-event.json") is None
    assert event_from_object_name("image.jpg") is None
