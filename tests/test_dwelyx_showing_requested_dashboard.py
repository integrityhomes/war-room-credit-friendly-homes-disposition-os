from datetime import UTC, datetime

from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionEvent,
    DwelyxEventType,
    JourneyStage,
    build_channel_attribution,
    build_funnel,
    build_journeys,
)


def showing_requested_event(event_id: str = "showing_event_123") -> DwelyxAttributionEvent:
    return DwelyxAttributionEvent(
        event_id=event_id,
        event_type=DwelyxEventType.SHOWING_REQUESTED,
        occurred_at=datetime(2026, 8, 11, 19, 0, tzinfo=UTC),
        dwelyx_buyer_id="buyer_test_123",
        cfh_property_id="property_test_123",
        source="credit_friendly_homes",
        medium="property_page",
        campaign="live_connection_test",
        test_mode=False,
    )


def test_showing_requested_counts_in_dashboard_and_channel() -> None:
    journeys = build_journeys([showing_requested_event()])

    assert len(journeys) == 1
    assert journeys[0].stage == JourneyStage.SHOWING_REQUESTED

    funnel = build_funnel(journeys)
    assert funnel.showings_requested == 1
    assert funnel.showings_scheduled == 1
    assert funnel.applications_submitted == 1

    channels = build_channel_attribution(journeys)
    property_page = next(row for row in channels if row.key == "property_page")
    assert property_page.showings == 1
    assert property_page.applications == 1


def test_duplicate_event_id_does_not_double_count_showing_metric() -> None:
    event = showing_requested_event()
    journeys = build_journeys([event, event])

    funnel = build_funnel(journeys)
    channels = build_channel_attribution(journeys)
    property_page = next(row for row in channels if row.key == "property_page")

    assert funnel.showings_scheduled == 1
    assert property_page.showings == 1
