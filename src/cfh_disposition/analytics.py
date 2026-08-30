from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .operational_failures import CriticalFailureType, record_operational_failure
from .storage import SupabaseSettings

CLICK_BUCKET = "cfh-click-events"
CLICK_PREFIX = "clicks"
CLICK_MAX_BYTES = 4096
DEFAULT_REPORT_DAYS = 30
LIVE_TRAFFIC = "live"
TEST_TRAFFIC = "test"
UNCLASSIFIED_TRAFFIC = "unclassified"
TRAFFIC_TYPES = {LIVE_TRAFFIC, TEST_TRAFFIC, UNCLASSIFIED_TRAFFIC}


class AnalyticsError(RuntimeError):
    """Raised when click analytics cannot be written or read."""


def normalize_traffic_type(value: Any) -> str:
    traffic_type = str(value or "").strip().lower()
    return traffic_type if traffic_type in TRAFFIC_TYPES else UNCLASSIFIED_TRAFFIC


@dataclass(frozen=True, slots=True)
class ClickEvent:
    occurred_at: datetime
    source: str
    medium: str
    campaign: str
    property_id: str | None = None
    traffic_type: str = UNCLASSIFIED_TRAFFIC

    @property
    def is_live(self) -> bool:
        return normalize_traffic_type(self.traffic_type) == LIVE_TRAFFIC

    @property
    def is_test(self) -> bool:
        return normalize_traffic_type(self.traffic_type) == TEST_TRAFFIC

    def to_payload(self) -> dict[str, str | None]:
        return {
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
            "source": self.source,
            "medium": self.medium,
            "campaign": self.campaign,
            "property_id": self.property_id,
            "traffic_type": normalize_traffic_type(self.traffic_type),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ClickEvent:
        occurred_at = datetime.fromisoformat(str(payload["occurred_at"]))
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return cls(
            occurred_at=occurred_at.astimezone(UTC),
            source=str(payload.get("source", "unknown")),
            medium=str(payload.get("medium", "unknown")),
            campaign=str(payload.get("campaign", "owner_finance_homes")),
            property_id=str(payload["property_id"]) if payload.get("property_id") else None,
            traffic_type=normalize_traffic_type(payload.get("traffic_type")),
        )


def live_click_events(events: list[ClickEvent]) -> list[ClickEvent]:
    """Return only clicks explicitly recorded as live buyer traffic."""
    return [event for event in events if event.is_live]


def traffic_type_counts(events: list[ClickEvent]) -> dict[str, int]:
    counts = Counter(normalize_traffic_type(event.traffic_type) for event in events)
    return {
        LIVE_TRAFFIC: counts[LIVE_TRAFFIC],
        TEST_TRAFFIC: counts[TEST_TRAFFIC],
        UNCLASSIFIED_TRAFFIC: counts[UNCLASSIFIED_TRAFFIC],
    }


def encode_event_token(event: ClickEvent) -> str:
    raw = json.dumps(event.to_payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_event_token(token: str) -> ClickEvent:
    padding = "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
    return ClickEvent.from_payload(payload)


def event_object_path(event: ClickEvent) -> str:
    timestamp = event.occurred_at.astimezone(UTC)
    token = encode_event_token(event)
    return (
        f"{CLICK_PREFIX}/{timestamp:%Y/%m/%d}/"
        f"{timestamp:%Y%m%dT%H%M%S%fZ}_{uuid4().hex}_{token}.json"
    )


def event_from_object_name(name: str) -> ClickEvent | None:
    file_name = name.rsplit("/", 1)[-1]
    if not file_name.endswith(".json"):
        return None
    stem = file_name[:-5]
    parts = stem.split("_", 2)
    if len(parts) != 3:
        return None
    try:
        return decode_event_token(parts[2])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error):
        return None


def click_summary(events: list[ClickEvent]) -> dict[str, Any]:
    source_counts = Counter(event.medium for event in events)
    campaign_counts = Counter(event.campaign for event in events)
    property_counts = Counter(event.property_id for event in events if event.property_id)
    return {
        "total": len(events),
        "sources": dict(source_counts.most_common()),
        "campaigns": dict(campaign_counts.most_common()),
        "properties": dict(property_counts.most_common()),
    }


class ClickAnalyticsStore:
    """Persistent, no-SQL click logging backed by a private Supabase Storage bucket."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise AnalyticsError("Supabase is not configured for click analytics.")
        self._values = values
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise AnalyticsError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(CLICK_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    CLICK_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": CLICK_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise AnalyticsError("Could not automatically create the click-analytics bucket.") from exc
        self._bucket_ready = True

    def record(self, event: ClickEvent) -> None:
        try:
            self._ensure_bucket()
            self._client.storage.from_(CLICK_BUCKET).upload(
                path=event_object_path(event),
                file=b"{}",
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "false",
                },
            )
        except Exception as exc:
            record_operational_failure(
                self._values,
                CriticalFailureType.LEAD_CAPTURE,
                summary="A tracked buyer click could not be written to attribution history.",
                technical_detail=str(exc),
                property_id=event.property_id or "",
                channel=event.medium,
                campaign=event.campaign,
                source=event.source,
            )
            raise AnalyticsError("Could not record the Dwelyx click.") from exc

    def list_recent(
        self,
        days: int = DEFAULT_REPORT_DAYS,
        *,
        include_test: bool = False,
        include_unclassified: bool = False,
    ) -> list[ClickEvent]:
        """List recent clicks, defaulting to verified live buyer traffic only.

        Legacy records created before traffic classification are intentionally excluded
        from production metrics unless ``include_unclassified`` is requested. Test clicks
        are also excluded unless ``include_test`` is requested.
        """
        self._ensure_bucket()
        days = max(1, min(days, 365))
        today = datetime.now(UTC).date()
        events: list[ClickEvent] = []
        bucket = self._client.storage.from_(CLICK_BUCKET)

        for offset in range(days):
            day = today - timedelta(days=offset)
            folder = f"{CLICK_PREFIX}/{day:%Y/%m/%d}"
            try:
                items = bucket.list(folder) or []
            except Exception:
                continue
            for item in items:
                name = item.get("name") if isinstance(item, Mapping) else None
                event = event_from_object_name(str(name)) if name else None
                if not event:
                    continue
                traffic_type = normalize_traffic_type(event.traffic_type)
                if traffic_type == TEST_TRAFFIC and not include_test:
                    continue
                if traffic_type == UNCLASSIFIED_TRAFFIC and not include_unclassified:
                    continue
                events.append(event)

        return sorted(events, key=lambda item: item.occurred_at, reverse=True)
