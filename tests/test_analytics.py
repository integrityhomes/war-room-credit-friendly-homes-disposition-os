from datetime import UTC, datetime

from cfh_disposition.analytics import (
    ClickEvent,
    click_summary,
    decode_event_token,
    encode_event_token,
    event_from_object_name,
    event_object_path,
)


def sample_event() -> ClickEvent:
    return ClickEvent(
        occurred_at=datetime(2026, 8, 3, 22, 30, tzinfo=UTC),
        source="credit_friendly_homes",
        medium="facebook_marketplace",
        campaign="owner_finance_homes",
        property_id="123-property",
    )


def test_event_token_round_trip():
    event = sample_event()
    restored = decode_event_token(encode_event_token(event))
    assert restored == event


def test_event_object_path_contains_date_and_decodes():
    event = sample_event()
    path = event_object_path(event)
    assert path.startswith("clicks/2026/08/03/")
    assert event_from_object_name(path) == event


def test_click_summary_groups_channels_campaigns_and_properties():
    event = sample_event()
    second = ClickEvent(
        occurred_at=event.occurred_at,
        source=event.source,
        medium="email",
        campaign=event.campaign,
        property_id=None,
    )
    summary = click_summary([event, event, second])
    assert summary["total"] == 3
    assert summary["sources"] == {"facebook_marketplace": 2, "email": 1}
    assert summary["campaigns"] == {"owner_finance_homes": 3}
    assert summary["properties"] == {"123-property": 2}


def test_invalid_object_name_is_ignored():
    assert event_from_object_name("not-an-event.json") is None
    assert event_from_object_name("image.jpg") is None
