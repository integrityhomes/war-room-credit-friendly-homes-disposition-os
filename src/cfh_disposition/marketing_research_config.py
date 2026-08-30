from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from .marketing_optimizer import MARKETING_OPTIMIZER_BUCKET, MARKETING_OPTIMIZER_MAX_BYTES
from .storage import SupabaseSettings

MARKETING_RESEARCH_CONFIG_PATH = "marketing-intelligence/research-targets.json"


class MarketingResearchConfigError(RuntimeError):
    """Raised when private marketing research configuration cannot be read or saved."""


class CompetitorResearchTarget(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_name: str = Field(min_length=2, max_length=200)
    market: str = Field(min_length=2, max_length=120)
    url: HttpUrl
    enabled: bool = True


class MarketingResearchConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    targets: list[CompetitorResearchTarget] = Field(default_factory=list, max_length=100)

    @property
    def enabled_targets(self) -> list[CompetitorResearchTarget]:
        return [target for target in self.targets if target.enabled]


class MarketingResearchConfigStore:
    """Private research-target configuration stored with existing marketing data."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise MarketingResearchConfigError("Supabase is not configured for marketing research.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise MarketingResearchConfigError("Supabase client is not installed.") from exc
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
                raise MarketingResearchConfigError("Could not prepare private marketing storage.") from exc
        self._bucket_ready = True

    def load(self) -> MarketingResearchConfig:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(MARKETING_OPTIMIZER_BUCKET).download(
                MARKETING_RESEARCH_CONFIG_PATH
            )
        except Exception:
            return MarketingResearchConfig()
        try:
            payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
            return MarketingResearchConfig.model_validate(payload)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MarketingResearchConfigError("Saved marketing research configuration could not be read.") from exc

    def save(self, config: MarketingResearchConfig) -> None:
        self._ensure_bucket()
        payload = config.model_dump_json().encode()
        if len(payload) > MARKETING_OPTIMIZER_MAX_BYTES:
            raise MarketingResearchConfigError("Marketing research configuration is too large to save.")
        try:
            self._client.storage.from_(MARKETING_OPTIMIZER_BUCKET).upload(
                path=MARKETING_RESEARCH_CONFIG_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise MarketingResearchConfigError("Could not save marketing research configuration.") from exc
