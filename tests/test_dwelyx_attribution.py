from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cfh_disposition.dwelyx_attribution import (
    DwelyxAttributionError,
    DwelyxAttributionEvent,
    DwelyxAttributionStore,
    DwelyxEventType,
    JourneyStage,
    build_channel_attribution,
    build_dwelyx_delivery,
    build_funnel,
    build_journeys,
    parse_signed_dwelyx_event,
    receiver_endpoint,
    sign_dwelyx_event,
)

NOW = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
SECRET = "test-shared-secret-with-enough-entropy"


def event_record(**overrides) -> DwelyxAttributionEvent:
    values = {
        "event_id": "event_12345678",
        "event_type": DwelyxEventType.BUYER_REGISTERED,
        "occurred_at": NOW,
        "dwelyx_buyer_id": "buyer_abc123",
        "source": "credit_friendly_homes",
        "medium": "nextdoor",
        "campaign": "saltville_august_2026",
        "dwelyx_record_url": "https://app.dwelyx.com/admin/buyers/buyer_abc123",
    }
    values.update(overrides)
    return DwelyxAttributionEvent(**values)


def signed_payload(event: DwelyxAttributionEvent, *, now: datetime = NOW):
    return build_dwelyx_delivery(event, SECRET, now=now)


def test_valid_signed_event_round_trips_without_personal_information() -> None:
    event = event_record()
    body, headers = signed_payload(event)

    parsed = parse_signed_dwelyx_event(body, headers, SECRET, now=NOW)

    assert parsed == event
    assert parsed.channel_key == "nextdoor"
    assert parsed.stage == JourneyStage.REGISTERED
    assert b"email" not in body
    assert b"phone" not in body
    assert headers["X-Dwelyx-Event-Id"] == event.event_id


def test_invalid_signature_is_rejected() -> None:
    event = event_record()
    body, headers = signed_payload(event)
    headers["X-Dwelyx-Signature"] = "sha256=bad"

    with pytest.raises(DwelyxAttributionError, match="signature is invalid"):
        parse_signed_dwelyx_event(body, headers, SECRET, now=NOW)


def test_stale_event_is_rejected_as_replay() -> None:
    event = event_record()
    body, headers = signed_payload(event, now=NOW - timedelta(minutes=10))

    with pytest.raises(DwelyxAttributionError, match="replay window"):
        parse_signed_dwelyx_event(body, headers, SECRET, now=NOW)


def test_personal_information_keys_are_rejected_before_contract_validation() -> None:
    payload = event_record().model_dump(mode="json")
    payload["email"] = "buyer@example.com"
    body = __import__("json").dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    timestamp = str(int(NOW.timestamp()))
    headers = {
        "X-Dwelyx-Event-Id": payload["event_id"],
        "X-Dwelyx-Timestamp": timestamp,
        "X-Dwelyx-Signature": sign_dwelyx_event(body, timestamp, SECRET),
    }

    with pytest.raises(DwelyxAttributionError, match="personal information"):
        parse_signed_dwelyx_event(body, headers, SECRET, now=NOW)


def test_event_id_header_must_match_body() -> None:
    event = event_record()
    body, headers = signed_payload(event)
    headers["X-Dwelyx-Event-Id"] = "different_event_id"

    with pytest.raises(DwelyxAttributionError, match="must match"):
        parse_signed_dwelyx_event(body, headers, SECRET, now=NOW)


def test_property_events_require_a_property_id() -> None:
    with pytest.raises(ValueError, match="requires a Dwelyx or Credit Friendly Homes property ID"):
        event_record(
            event_type=DwelyxEventType.APPLICATION_SUBMITTED,
            dwelyx_property_id="",
            cfh_property_id="",
        )


def test_dwelyx_deep_link_rejects_other_hosts() -> None:
    with pytest.raises(ValueError, match="dwelyx.com"):
        event_record(dwelyx_record_url="https://example.com/admin/buyers/buyer_abc123")


def test_out_of_order_events_keep_highest_stage_and_known_attribution() -> None:
    registration = event_record(
        event_id="event_registration_1",
        occurred_at=NOW,
        medium="unknown",
        dwelyx_record_url="",
    )
    application = event_record(
        event_id="event_application_1",
        event_type=DwelyxEventType.APPLICATION_SUBMITTED,
        occurred_at=NOW + timedelta(hours=2),
        medium="nextdoor",
        cfh_property_id="property_123",
    )
    contract = event_record(
        event_id="event_contract_1",
        event_type=DwelyxEventType.CONTRACT_SIGNED,
        occurred_at=NOW + timedelta(hours=1),
        medium="unknown",
        cfh_property_id="property_123",
    )

    journeys = build_journeys([application, registration, contract])

    assert len(journeys) == 2
    property_journey = next(item for item in journeys if item.cfh_property_id == "property_123")
    assert property_journey.stage == JourneyStage.CONTRACT_SIGNED
    assert property_journey.channel_key == "nextdoor"
    assert property_journey.event_count == 2


def test_funnel_counts_unique_journeys_cumulatively() -> None:
    events = [
        event_record(event_id="event_a_registered", dwelyx_buyer_id="buyer_a"),
        event_record(
            event_id="event_a_application",
            event_type=DwelyxEventType.APPLICATION_SUBMITTED,
            occurred_at=NOW + timedelta(minutes=1),
            dwelyx_buyer_id="buyer_a",
            cfh_property_id="property_1",
        ),
        event_record(
            event_id="event_a_contract",
            event_type=DwelyxEventType.CONTRACT_SIGNED,
            occurred_at=NOW + timedelta(minutes=2),
            dwelyx_buyer_id="buyer_a",
            cfh_property_id="property_1",
        ),
        event_record(
            event_id="event_a_filled",
            event_type=DwelyxEventType.HOME_FILLED,
            occurred_at=NOW + timedelta(minutes=3),
            dwelyx_buyer_id="buyer_a",
            cfh_property_id="property_1",
        ),
        event_record(
            event_id="event_b_registered",
            dwelyx_buyer_id="buyer_b",
            medium="google_ads",
        ),
    ]

    funnel = build_funnel(build_journeys(events))

    assert funnel.journeys == 3
    assert funnel.registrations == 3
    assert funnel.applications_submitted == 1
    assert funnel.contracts_signed == 1
    assert funnel.filled == 1
    assert funnel.registration_to_application_rate == pytest.approx(1 / 3)
    assert funnel.application_to_contract_rate == 1.0
    assert funnel.contract_to_filled_rate == 1.0


def test_channel_attribution_always_includes_all_15_channels() -> None:
    journey = build_journeys(
        [
            event_record(
                event_id="event_nextdoor_application",
                event_type=DwelyxEventType.APPLICATION_SUBMITTED,
                cfh_property_id="property_1",
            )
        ]
    )

    rows = build_channel_attribution(journey)

    assert len(rows) == 15
    nextdoor = next(row for row in rows if row.key == "nextdoor")
    assert nextdoor.registrations == 1
    assert nextdoor.applications == 1
    assert nextdoor.contracts == 0
    assert sum(row.registrations for row in rows) == 1


class FakeBucket:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def download(self, path: str):
        if path not in self.files:
            raise RuntimeError("missing")
        return self.files[path]

    def upload(self, *, path: str, file: bytes, file_options):
        if path in self.files and file_options.get("upsert") == "false":
            raise RuntimeError("duplicate")
        self.files[path] = file

    def list(self, prefix: str, options=None):
        prefix_with_slash = f"{prefix}/"
        return [
            {"name": path[len(prefix_with_slash) :]}
            for path in sorted(self.files, reverse=True)
            if path.startswith(prefix_with_slash)
        ]


class FakeStorageApi:
    def __init__(self) -> None:
        self.bucket = FakeBucket()
        self.created = False

    def get_bucket(self, name: str):
        if not self.created:
            raise RuntimeError("missing")
        return {"name": name}

    def create_bucket(self, name: str, options):
        self.created = True
        return {"name": name, "options": options}

    def from_(self, name: str):
        return self.bucket


class FakeClient:
    def __init__(self) -> None:
        self.storage = FakeStorageApi()


def test_private_store_is_idempotent_and_lists_saved_events() -> None:
    client = FakeClient()
    store = DwelyxAttributionStore(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "secret",
        },
        client=client,
    )
    event = event_record()

    assert store.record(event) is True
    assert store.record(event) is False
    assert store.list_events() == [event]
    assert client.storage.created is True


def test_receiver_endpoint_uses_supabase_url_or_explicit_override() -> None:
    assert receiver_endpoint({"SUPABASE_URL": "https://project.supabase.co"}) == "https://project.supabase.co/functions/v1/dwelyx-results"
    assert receiver_endpoint(
        {
            "SUPABASE_URL": "https://project.supabase.co",
            "DWELYX_RESULTS_ENDPOINT": "https://receiver.example.com/dwelyx",
        }
    ) == "https://receiver.example.com/dwelyx"


def test_edge_receiver_source_enforces_signature_privacy_and_idempotency() -> None:
    source = Path("supabase/functions/dwelyx-results/index.ts").read_text(encoding="utf-8")

    assert "x-dwelyx-signature" in source
    assert "REPLAY_WINDOW_SECONDS" in source
    assert "PROHIBITED_KEYS" in source
    assert "upsert: false" in source
    assert "SUPABASE_SERVICE_ROLE_KEY" in source
    assert "buyer personal information" in source.lower()
