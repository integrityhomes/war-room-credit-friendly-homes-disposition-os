from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .marketing_intelligence import MarketObservation
from .marketing_optimizer import MARKETING_OPTIMIZER_BUCKET, MARKETING_OPTIMIZER_MAX_BYTES
from .storage import SupabaseSettings

MARKETING_INTELLIGENCE_PATH = "marketing-intelligence/observations.json"


class MarketingIntelligenceStoreError(RuntimeError):
    """Raised when the private marketing-intelligence ledger cannot be read or saved."""


class StoredMarketObservation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    observation: MarketObservation
    first_seen_at: datetime
    last_seen_at: datetime
    sightings: int = Field(default=1, ge=1)


class MarketingIntelligenceLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observations: list[StoredMarketObservation] = Field(default_factory=list)


def observation_identity(observation: MarketObservation) -> tuple[str, str, str, str]:
    return (
        observation.surface.value,
        " ".join(observation.market.casefold().split()),
        str(observation.source_url or observation.source_name).casefold(),
        " ".join(observation.headline_or_topic.casefold().split()),
    )


def upsert_observation(
    ledger: MarketingIntelligenceLedger,
    observation: MarketObservation,
    *,
    observed_at: datetime | None = None,
) -> MarketingIntelligenceLedger:
    timestamp = observed_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    wanted = observation_identity(observation)

    updated: list[StoredMarketObservation] = []
    matched = False
    for item in ledger.observations:
        if observation_identity(item.observation) != wanted:
            updated.append(item)
            continue
        matched = True
        updated.append(
            item.model_copy(
                update={
                    "observation": observation,
                    "last_seen_at": timestamp,
                    "sightings": item.sightings + 1,
                }
            )
        )

    if not matched:
        updated.append(
            StoredMarketObservation(
                observation=observation,
                first_seen_at=timestamp,
                last_seen_at=timestamp,
            )
        )

    return ledger.model_copy(update={"updated_at": timestamp, "observations": updated})


class MarketingIntelligenceStore:
    """Private learning ledger stored in the existing marketing Supabase bucket."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise MarketingIntelligenceStoreError(
                "Supabase is not configured for the marketing intelligence ledger."
            )
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise MarketingIntelligenceStoreError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(MARKETING_OPTIMIZER_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    MARKETING_OPTIMIZER_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": MARKETING_OPTIMIZER_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise MarketingIntelligenceStoreError(
                    "Could not prepare the private marketing storage bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> MarketingIntelligenceLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(MARKETING_OPTIMIZER_BUCKET).download(
                MARKETING_INTELLIGENCE_PATH
            )
        except Exception:
            return MarketingIntelligenceLedger()
        try:
            payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
            return MarketingIntelligenceLedger.model_validate(payload)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MarketingIntelligenceStoreError(
                "The saved marketing intelligence ledger could not be read."
            ) from exc

    def save(self, ledger: MarketingIntelligenceLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > MARKETING_OPTIMIZER_MAX_BYTES:
            raise MarketingIntelligenceStoreError(
                "The marketing intelligence ledger is too large to save."
            )
        try:
            self._client.storage.from_(MARKETING_OPTIMIZER_BUCKET).upload(
                path=MARKETING_INTELLIGENCE_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise MarketingIntelligenceStoreError(
                "Could not save the marketing intelligence ledger."
            ) from exc
