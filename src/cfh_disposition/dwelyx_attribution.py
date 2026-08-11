from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .channel_tracking import canonical_channel_key, channel_name
from .channels import CHANNELS
from .storage import SupabaseSettings

DWELYX_ATTRIBUTION_BUCKET = "cfh-dwelyx-attribution"
DWELYX_ATTRIBUTION_PREFIX = "events"
DWELYX_ATTRIBUTION_MAX_BYTES = 16 * 1024
DWELYX_SCHEMA_VERSION = "1.0"
DWELYX_SIGNATURE_HEADER = "x-dwelyx-signature"
DWELYX_TIMESTAMP_HEADER = "x-dwelyx-timestamp"
DWELYX_EVENT_ID_HEADER = "x-dwelyx-event-id"
DEFAULT_REPLAY_WINDOW_SECONDS = 300
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")

PROHIBITED_PAYLOAD_KEYS = {
    "name",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "email_address",
    "phone",
    "phone_number",
    "mobile",
    "address",
    "street_address",
    "date_of_birth",
    "dob",
    "ssn",
    "social_security_number",
    "income",
    "employer",
    "application_data",
    "documents",
    "document_url",
    "credit_score",
    "bank_account",
}


class DwelyxAttributionError(RuntimeError):
    """Raised when a Dwelyx event is invalid, unsafe, or cannot be stored."""


class DwelyxEventType(StrEnum):
    BUYER_REGISTERED = "buyer.registered"
    BUYER_QUALIFIED = "buyer.qualified"
    APPLICATION_STARTED = "application.started"
    APPLICATION_SUBMITTED = "application.submitted"
    SHOWING_REQUESTED = "showing.requested"
    SHOWING_SCHEDULED = "showing.scheduled"
    CONTRACT_PENDING = "contract.pending"
    CONTRACT_SIGNED = "contract.signed"
    HOME_FILLED = "home.filled"


class JourneyStage(StrEnum):
    REGISTERED = "Registered"
    QUALIFIED = "Qualified"
    APPLICATION_STARTED = "Application Started"
    APPLICATION_SUBMITTED = "Application Submitted"
    SHOWING_REQUESTED = "Showing Requested"
    SHOWING_SCHEDULED = "Showing Scheduled"
    CONTRACT_PENDING = "Contract Pending"
    CONTRACT_SIGNED = "Contract Signed"
    FILLED = "Filled"


STAGE_BY_EVENT: dict[DwelyxEventType, JourneyStage] = {
    DwelyxEventType.BUYER_REGISTERED: JourneyStage.REGISTERED,
    DwelyxEventType.BUYER_QUALIFIED: JourneyStage.QUALIFIED,
    DwelyxEventType.APPLICATION_STARTED: JourneyStage.APPLICATION_STARTED,
    DwelyxEventType.APPLICATION_SUBMITTED: JourneyStage.APPLICATION_SUBMITTED,
    DwelyxEventType.SHOWING_REQUESTED: JourneyStage.SHOWING_REQUESTED,
    DwelyxEventType.SHOWING_SCHEDULED: JourneyStage.SHOWING_SCHEDULED,
    DwelyxEventType.CONTRACT_PENDING: JourneyStage.CONTRACT_PENDING,
    DwelyxEventType.CONTRACT_SIGNED: JourneyStage.CONTRACT_SIGNED,
    DwelyxEventType.HOME_FILLED: JourneyStage.FILLED,
}

STAGE_RANK: dict[JourneyStage, int] = {
    JourneyStage.REGISTERED: 1,
    JourneyStage.QUALIFIED: 2,
    JourneyStage.APPLICATION_STARTED: 3,
    JourneyStage.APPLICATION_SUBMITTED: 4,
    JourneyStage.SHOWING_REQUESTED: 5,
    JourneyStage.SHOWING_SCHEDULED: 6,
    JourneyStage.CONTRACT_PENDING: 7,
    JourneyStage.CONTRACT_SIGNED: 8,
    JourneyStage.FILLED: 9,
}

PROPERTY_REQUIRED_EVENTS = {
    DwelyxEventType.APPLICATION_STARTED,
    DwelyxEventType.APPLICATION_SUBMITTED,
    DwelyxEventType.SHOWING_REQUESTED,
    DwelyxEventType.SHOWING_SCHEDULED,
    DwelyxEventType.CONTRACT_PENDING,
    DwelyxEventType.CONTRACT_SIGNED,
    DwelyxEventType.HOME_FILLED,
}


class DwelyxAttributionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: str = DWELYX_SCHEMA_VERSION
    event_id: str = Field(min_length=8, max_length=200)
    event_type: DwelyxEventType
    occurred_at: datetime
    dwelyx_buyer_id: str = Field(min_length=3, max_length=200)
    dwelyx_property_id: str = Field(default="", max_length=200)
    cfh_property_id: str = Field(default="", max_length=200)
    source: str = Field(default="credit_friendly_homes", max_length=100)
    medium: str = Field(default="unknown", max_length=100)
    campaign: str = Field(default="owner_finance_homes", max_length=180)
    dwelyx_record_url: str = Field(default="", max_length=1000)
    test_mode: bool = False

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("event_id", "dwelyx_buyer_id", "dwelyx_property_id", "cfh_property_id")
    @classmethod
    def validate_safe_ids(cls, value: str) -> str:
        if value and not SAFE_ID_PATTERN.fullmatch(value):
            raise ValueError("IDs may contain only letters, numbers, periods, underscores, colons, and hyphens")
        return value

    @field_validator("dwelyx_record_url")
    @classmethod
    def validate_dwelyx_record_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (hostname == "dwelyx.com" or hostname.endswith(".dwelyx.com")):
            raise ValueError("Dwelyx record links must use HTTPS on dwelyx.com")
        return value

    @model_validator(mode="after")
    def validate_event_contract(self) -> DwelyxAttributionEvent:
        if self.schema_version != DWELYX_SCHEMA_VERSION:
            raise ValueError("Unsupported Dwelyx event schema version")
        if self.event_type in PROPERTY_REQUIRED_EVENTS and not (self.dwelyx_property_id or self.cfh_property_id):
            raise ValueError("This Dwelyx event requires a Dwelyx or Credit Friendly Homes property ID")
        return self

    @property
    def stage(self) -> JourneyStage:
        return STAGE_BY_EVENT[self.event_type]

    @property
    def journey_property_id(self) -> str:
        return self.cfh_property_id or self.dwelyx_property_id or "unassigned"

    @property
    def journey_key(self) -> str:
        return f"{self.dwelyx_buyer_id}|{self.journey_property_id}"

    @property
    def channel_key(self) -> str:
        return canonical_channel_key(self.medium) or "unmapped"

    @property
    def channel_display_name(self) -> str:
        return channel_name(self.medium) if self.channel_key != "unmapped" else "Unmapped / Direct"


@dataclass(frozen=True, slots=True)
class JourneySnapshot:
    journey_key: str
    dwelyx_buyer_id: str
    dwelyx_property_id: str
    cfh_property_id: str
    source: str
    channel_key: str
    channel_name: str
    campaign: str
    stage: JourneyStage
    first_event_at: datetime
    latest_event_at: datetime
    event_count: int
    dwelyx_record_url: str
    test_mode: bool


@dataclass(frozen=True, slots=True)
class FunnelSnapshot:
    journeys: int
    registrations: int
    qualified: int
    applications_started: int
    applications_submitted: int
    showings_requested: int
    showings_scheduled: int
    contracts_pending: int
    contracts_signed: int
    filled: int
    registration_to_application_rate: float
    application_to_contract_rate: float
    contract_to_filled_rate: float


@dataclass(frozen=True, slots=True)
class AttributionRow:
    key: str
    name: str
    journeys: int
    registrations: int
    applications: int
    showings: int
    contracts: int
    filled: int
    registration_to_application_rate: float
    application_to_contract_rate: float
    latest_result_at: datetime | None


def _current(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(UTC)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=UTC)


def _normalized_header_map(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).strip().lower(): str(value).strip() for key, value in headers.items()}


def _payload_key_violations(value: Any, prefix: str = "") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            path = f"{prefix}.{normalized}" if prefix else normalized
            if normalized in PROHIBITED_PAYLOAD_KEYS:
                violations.append(path)
            violations.extend(_payload_key_violations(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(_payload_key_violations(nested, f"{prefix}[{index}]"))
    return violations


def serialize_dwelyx_event(event: DwelyxAttributionEvent) -> bytes:
    payload = event.model_dump(mode="json")
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def sign_dwelyx_event(body: bytes, timestamp: str, secret: str) -> str:
    if not secret:
        raise DwelyxAttributionError("DWELYX_WEBHOOK_SECRET is required to sign events")
    signed = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_dwelyx_delivery(
    event: DwelyxAttributionEvent,
    secret: str,
    *,
    now: datetime | None = None,
) -> tuple[bytes, dict[str, str]]:
    current = _current(now)
    timestamp = str(int(current.timestamp()))
    body = serialize_dwelyx_event(event)
    return body, {
        "Content-Type": "application/json",
        "X-Dwelyx-Event-Id": event.event_id,
        "X-Dwelyx-Timestamp": timestamp,
        "X-Dwelyx-Signature": sign_dwelyx_event(body, timestamp, secret),
    }


def verify_dwelyx_signature(
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now: datetime | None = None,
    replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
) -> None:
    if not secret:
        raise DwelyxAttributionError("DWELYX_WEBHOOK_SECRET is not configured")
    normalized = _normalized_header_map(headers)
    timestamp_text = normalized.get(DWELYX_TIMESTAMP_HEADER, "")
    received_signature = normalized.get(DWELYX_SIGNATURE_HEADER, "")
    if not timestamp_text or not received_signature:
        raise DwelyxAttributionError("Dwelyx timestamp and signature headers are required")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise DwelyxAttributionError("Dwelyx timestamp header is invalid") from exc
    current = _current(now)
    if abs(int(current.timestamp()) - timestamp) > max(30, replay_window_seconds):
        raise DwelyxAttributionError("Dwelyx event timestamp is outside the allowed replay window")
    expected = sign_dwelyx_event(body, timestamp_text, secret)
    if not hmac.compare_digest(received_signature, expected):
        raise DwelyxAttributionError("Dwelyx event signature is invalid")


def parse_signed_dwelyx_event(
    body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now: datetime | None = None,
) -> DwelyxAttributionEvent:
    if not body:
        raise DwelyxAttributionError("Dwelyx event body is empty")
    if len(body) > DWELYX_ATTRIBUTION_MAX_BYTES:
        raise DwelyxAttributionError("Dwelyx event body is too large")
    verify_dwelyx_signature(body, headers, secret, now=now)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DwelyxAttributionError("Dwelyx event body is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise DwelyxAttributionError("Dwelyx event body must be a JSON object")
    violations = _payload_key_violations(payload)
    if violations:
        raise DwelyxAttributionError(
            "Buyer personal information is not allowed in the attribution event: " + ", ".join(sorted(set(violations)))
        )
    try:
        event = DwelyxAttributionEvent.model_validate(payload)
    except ValueError as exc:
        raise DwelyxAttributionError(f"Dwelyx event failed contract validation: {exc}") from exc
    normalized = _normalized_header_map(headers)
    header_event_id = normalized.get(DWELYX_EVENT_ID_HEADER, "")
    if not header_event_id or header_event_id != event.event_id:
        raise DwelyxAttributionError("Dwelyx event ID header must match the event body")
    return event


def attribution_event_for_journey(events: Sequence[DwelyxAttributionEvent]) -> DwelyxAttributionEvent:
    ordered = sorted(events, key=lambda item: item.occurred_at)
    return next((event for event in ordered if canonical_channel_key(event.medium)), ordered[0])


def build_journeys(events: Sequence[DwelyxAttributionEvent]) -> list[JourneySnapshot]:
    grouped: dict[str, list[DwelyxAttributionEvent]] = defaultdict(list)
    for event in events:
        grouped[event.journey_key].append(event)
    journeys: list[JourneySnapshot] = []
    for journey_key, journey_events in grouped.items():
        ordered = sorted(journey_events, key=lambda item: item.occurred_at)
        attribution = attribution_event_for_journey(ordered)
        highest = max(ordered, key=lambda item: (STAGE_RANK[item.stage], item.occurred_at))
        latest = max(ordered, key=lambda item: item.occurred_at)
        deep_link = next((event.dwelyx_record_url for event in reversed(ordered) if event.dwelyx_record_url), "")
        journeys.append(
            JourneySnapshot(
                journey_key=journey_key,
                dwelyx_buyer_id=latest.dwelyx_buyer_id,
                dwelyx_property_id=next((event.dwelyx_property_id for event in reversed(ordered) if event.dwelyx_property_id), ""),
                cfh_property_id=next((event.cfh_property_id for event in reversed(ordered) if event.cfh_property_id), ""),
                source=attribution.source,
                channel_key=attribution.channel_key,
                channel_name=attribution.channel_display_name,
                campaign=attribution.campaign,
                stage=highest.stage,
                first_event_at=ordered[0].occurred_at,
                latest_event_at=latest.occurred_at,
                event_count=len(ordered),
                dwelyx_record_url=deep_link,
                test_mode=all(event.test_mode for event in ordered),
            )
        )
    return sorted(journeys, key=lambda item: item.latest_event_at, reverse=True)


def _reached(journey: JourneySnapshot, stage: JourneyStage) -> bool:
    return STAGE_RANK[journey.stage] >= STAGE_RANK[stage]


def build_funnel(journeys: Sequence[JourneySnapshot]) -> FunnelSnapshot:
    registrations = sum(_reached(item, JourneyStage.REGISTERED) for item in journeys)
    qualified = sum(_reached(item, JourneyStage.QUALIFIED) for item in journeys)
    applications_started = sum(_reached(item, JourneyStage.APPLICATION_STARTED) for item in journeys)
    applications_submitted = sum(_reached(item, JourneyStage.APPLICATION_SUBMITTED) for item in journeys)
    showings_requested = sum(_reached(item, JourneyStage.SHOWING_REQUESTED) for item in journeys)
    # The Results Dashboard's "Showings" metric represents showing requests (or any later showing stage).
    # Keep the legacy field name for compatibility with the Streamlit page while counting from SHOWING_REQUESTED.
    showings_scheduled = showings_requested
    contracts_pending = sum(_reached(item, JourneyStage.CONTRACT_PENDING) for item in journeys)
    contracts_signed = sum(_reached(item, JourneyStage.CONTRACT_SIGNED) for item in journeys)
    filled = sum(_reached(item, JourneyStage.FILLED) for item in journeys)
    return FunnelSnapshot(
        journeys=len(journeys),
        registrations=registrations,
        qualified=qualified,
        applications_started=applications_started,
        applications_submitted=applications_submitted,
        showings_requested=showings_requested,
        showings_scheduled=showings_scheduled,
        contracts_pending=contracts_pending,
        contracts_signed=contracts_signed,
        filled=filled,
        registration_to_application_rate=(applications_submitted / registrations if registrations else 0.0),
        application_to_contract_rate=(contracts_signed / applications_submitted if applications_submitted else 0.0),
        contract_to_filled_rate=(filled / contracts_signed if contracts_signed else 0.0),
    )


def _attribution_row(key: str, name: str, journeys: Sequence[JourneySnapshot]) -> AttributionRow:
    registrations = sum(_reached(item, JourneyStage.REGISTERED) for item in journeys)
    applications = sum(_reached(item, JourneyStage.APPLICATION_SUBMITTED) for item in journeys)
    showings = sum(_reached(item, JourneyStage.SHOWING_REQUESTED) for item in journeys)
    contracts = sum(_reached(item, JourneyStage.CONTRACT_SIGNED) for item in journeys)
    filled = sum(_reached(item, JourneyStage.FILLED) for item in journeys)
    return AttributionRow(
        key=key,
        name=name,
        journeys=len(journeys),
        registrations=registrations,
        applications=applications,
        showings=showings,
        contracts=contracts,
        filled=filled,
        registration_to_application_rate=(applications / registrations if registrations else 0.0),
        application_to_contract_rate=(contracts / applications if applications else 0.0),
        latest_result_at=max((item.latest_event_at for item in journeys), default=None),
    )


def build_channel_attribution(journeys: Sequence[JourneySnapshot]) -> list[AttributionRow]:
    grouped: dict[str, list[JourneySnapshot]] = defaultdict(list)
    for journey in journeys:
        grouped[journey.channel_key].append(journey)
    rows = [_attribution_row(channel.key, channel.name, grouped[channel.key]) for channel in CHANNELS]
    if grouped.get("unmapped"):
        rows.append(_attribution_row("unmapped", "Unmapped / Direct", grouped["unmapped"]))
    return rows


def build_campaign_attribution(journeys: Sequence[JourneySnapshot]) -> list[AttributionRow]:
    grouped: dict[str, list[JourneySnapshot]] = defaultdict(list)
    for journey in journeys:
        grouped[journey.campaign or "unknown"].append(journey)
    rows = [_attribution_row(key, key, values) for key, values in grouped.items()]
    return sorted(rows, key=lambda item: (-item.filled, -item.contracts, -item.applications, -item.registrations, item.name.casefold()))


def build_property_attribution(journeys: Sequence[JourneySnapshot]) -> list[AttributionRow]:
    grouped: dict[str, list[JourneySnapshot]] = defaultdict(list)
    for journey in journeys:
        key = journey.cfh_property_id or journey.dwelyx_property_id or "unassigned"
        grouped[key].append(journey)
    rows = [_attribution_row(key, key, values) for key, values in grouped.items()]
    return sorted(rows, key=lambda item: (-item.filled, -item.contracts, -item.applications, -item.registrations, item.name.casefold()))


def attribution_rows(rows: Sequence[AttributionRow]) -> list[dict[str, str | int]]:
    return [
        {
            "Source": row.name,
            "Registrations": row.registrations,
            "Applications": row.applications,
            "Showings": row.showings,
            "Contracts": row.contracts,
            "Filled Homes": row.filled,
            "Registration → Application": f"{row.registration_to_application_rate:.1%}",
            "Application → Contract": f"{row.application_to_contract_rate:.1%}",
            "Latest Result": row.latest_result_at.astimezone().strftime("%Y-%m-%d %I:%M %p") if row.latest_result_at else "—",
        }
        for row in rows
    ]


def journey_rows(journeys: Sequence[JourneySnapshot], property_labels: Mapping[str, str] | None = None) -> list[dict[str, str | int]]:
    labels = property_labels or {}
    return [
        {
            "Dwelyx Buyer ID": journey.dwelyx_buyer_id,
            "Property": labels.get(journey.cfh_property_id, journey.cfh_property_id or journey.dwelyx_property_id or "Unassigned"),
            "Channel": journey.channel_name,
            "Campaign": journey.campaign,
            "Current Stage": journey.stage.value,
            "Events": journey.event_count,
            "First Result": journey.first_event_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Latest Result": journey.latest_event_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Test": "Yes" if journey.test_mode else "No",
        }
        for journey in journeys
    ]


def event_rows(events: Sequence[DwelyxAttributionEvent], property_labels: Mapping[str, str] | None = None) -> list[dict[str, str]]:
    labels = property_labels or {}
    return [
        {
            "When": event.occurred_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
            "Event": event.event_type.value,
            "Stage": event.stage.value,
            "Dwelyx Buyer ID": event.dwelyx_buyer_id,
            "Property": labels.get(event.cfh_property_id, event.cfh_property_id or event.dwelyx_property_id or "Unassigned"),
            "Channel": event.channel_display_name,
            "Campaign": event.campaign,
            "Test": "Yes" if event.test_mode else "No",
            "Event ID": event.event_id,
        }
        for event in sorted(events, key=lambda item: item.occurred_at, reverse=True)
    ]


def receiver_endpoint(values: Mapping[str, Any]) -> str:
    explicit = str(values.get("DWELYX_RESULTS_ENDPOINT", "")).strip()
    if explicit:
        return explicit
    settings = SupabaseSettings.from_mapping(values)
    return f"{settings.url.rstrip('/')}/functions/v1/dwelyx-results" if settings.url else ""


class DwelyxAttributionStore:
    """Private, one-object-per-event Supabase Storage inbox with duplicate protection."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise DwelyxAttributionError("Supabase is not configured for Dwelyx attribution events")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise DwelyxAttributionError("Supabase client is not installed") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(DWELYX_ATTRIBUTION_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    DWELYX_ATTRIBUTION_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": DWELYX_ATTRIBUTION_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise DwelyxAttributionError("Could not create the private Dwelyx attribution bucket") from exc
        self._bucket_ready = True

    @staticmethod
    def _event_path(event_id: str) -> str:
        return f"{DWELYX_ATTRIBUTION_PREFIX}/{event_id}.json"

    def record(self, event: DwelyxAttributionEvent) -> bool:
        self._ensure_bucket()
        bucket = self._client.storage.from_(DWELYX_ATTRIBUTION_BUCKET)
        path = self._event_path(event.event_id)
        try:
            bucket.download(path)
            return False
        except Exception:
            pass
        payload = serialize_dwelyx_event(event)
        try:
            bucket.upload(
                path=path,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "false",
                },
            )
            return True
        except Exception as exc:
            try:
                bucket.download(path)
                return False
            except Exception:
                raise DwelyxAttributionError("Could not store the Dwelyx attribution event") from exc

    def list_events(self, limit: int = 2000) -> list[DwelyxAttributionEvent]:
        self._ensure_bucket()
        maximum = max(1, min(limit, 10000))
        bucket = self._client.storage.from_(DWELYX_ATTRIBUTION_BUCKET)
        items: list[Any] = []
        offset = 0
        page_size = min(100, maximum)
        while len(items) < maximum:
            try:
                page = bucket.list(
                    DWELYX_ATTRIBUTION_PREFIX,
                    {"limit": page_size, "offset": offset, "sortBy": {"column": "name", "order": "desc"}},
                ) or []
            except TypeError:
                page = bucket.list(DWELYX_ATTRIBUTION_PREFIX) or []
            except Exception as exc:
                raise DwelyxAttributionError("Could not list Dwelyx attribution events") from exc
            items.extend(page)
            if len(page) < page_size or isinstance(page, list) and offset > 0 and not page:
                break
            if len(items) >= maximum or offset > 0 and len(page) == len(items):
                break
            offset += len(page)
        events: list[DwelyxAttributionEvent] = []
        for item in items[:maximum]:
            name = item.get("name") if isinstance(item, Mapping) else None
            if not name or not str(name).endswith(".json"):
                continue
            path = f"{DWELYX_ATTRIBUTION_PREFIX}/{name}"
            try:
                raw = bucket.download(path)
                payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                events.append(DwelyxAttributionEvent.model_validate_json(payload))
            except Exception:
                continue
        return sorted(events, key=lambda item: item.occurred_at, reverse=True)
