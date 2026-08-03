from __future__ import annotations

import base64
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .storage import SupabaseSettings

CLICK_BUCKET = "cfh-click-events"
CLICK_PREFIX = "clicks"
CLICK_MAX_BYTES = 4096
DEFAULT_REPORT_DAYS = 30


class AnalyticsError(RuntimeError):
    """Raised when click analytics cannot be written or read."""


@dataclass(frozen=True, slots=True)
class ClickEvent:
    occurred_at: datetime
    source: str
    medium: str
    campaign: str
    property_id: str | None = None

    def to_payload(self) -> dict[str, str | None]:
        return {
            "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat(),
            "source": self.source,
            "medium": self.medium,
            "campaign": self.campaign,
            "property_id": self.property_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ClickEvent:
        occurred_at = datetime.fromisoformat(str(payload["occurred_at"]))
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        return cls(
            occurred_at=occurred_at.astimezone(timezone.utc),
            source=str(payload.get("source", "unknown")),
            medium=str(payload.get("medium", "unknown")),
            campaign=str(payload.get("campaign", "owner_finance_homes")),
            property_id=str(payload["property_id"]) if payload.get("property_id") else None,
        )


def encode_event_token(event: ClickEvent) -> str:
    raw = json.dumps(event.to_payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_event_token(token: str) -> ClickEvent:
    padding = "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
    return ClickEvent.from_payload(payload)


def event_object_path(event: ClickEvent) -> str:
    timestamp = event.occurred_at.astimezone(timezone.utc)
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
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
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
        self._ensure_bucket()
        try:
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
            raise AnalyticsError("Could not record the Dwelyx click.") from exc

    def list_recent(self, days: int = DEFAULT_REPORT_DAYS) -> list[ClickEvent]:
        self._ensure_bucket()
        days = max(1, min(days, 365))
        today = datetime.now(timezone.utc).date()
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
                if event:
                    events.append(event)

        return sorted(events, key=lambda item: item.occurred_at, reverse=True)
