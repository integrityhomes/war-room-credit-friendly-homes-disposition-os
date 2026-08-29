from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from .storage import SupabaseSettings

FAILURE_BUCKET = "cfh-operational-failures"
FAILURE_LEDGER_PATH = "operations/failure-learning-ledger.json"
FAILURE_MAX_BYTES = 4 * 1024 * 1024


class OperationalFailureError(RuntimeError):
    """Raised when the critical failure ledger cannot be read or written."""


class CriticalFailureType(StrEnum):
    EMAIL = "Email"
    SMS = "SMS"
    LANDING_PAGE_SUBMIT = "Landing-page submit"
    FACEBOOK_TASK = "Facebook task"
    LEAD_CAPTURE = "Lead capture / attribution"
    SOLD_SHUTDOWN = "Sold-shutdown"


class FailureStatus(StrEnum):
    OPEN = "Open"
    RESOLVED = "Resolved"
    MANUAL_OVERRIDE = "Manual Override"


class OperationalFailure(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    failure_id: str = Field(default_factory=lambda: str(uuid4()))
    failure_type: CriticalFailureType
    status: FailureStatus = FailureStatus.OPEN
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    property_id: str = ""
    property_address: str = ""
    channel: str = ""
    campaign: str = "owner_finance_homes"
    source: str = ""
    buyer_id: str = ""
    summary: str = Field(min_length=3, max_length=600)
    technical_detail: str = Field(default="", max_length=3000)
    root_cause: str = Field(default="Unknown", max_length=1200)
    resolution: str = Field(default="", max_length=1200)
    prevention_note: str = Field(default="", max_length=1200)
    occurrence_key: str = Field(default="", max_length=500)
    repeat_count: int = Field(default=1, ge=1)
    resolved_at: datetime | None = None
    resolved_by: str = ""


class OperationalFailureLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    failures: list[OperationalFailure] = Field(default_factory=list)


def _occurrence_key(
    failure_type: CriticalFailureType,
    *,
    property_id: str = "",
    channel: str = "",
    campaign: str = "",
    source: str = "",
) -> str:
    return "|".join(
        [failure_type.value, property_id, channel, campaign, source]
    ).casefold()


def append_failure(
    ledger: OperationalFailureLedger,
    failure: OperationalFailure,
) -> OperationalFailureLedger:
    failures = list(ledger.failures)
    if failure.occurrence_key:
        for index in range(len(failures) - 1, -1, -1):
            existing = failures[index]
            if (
                existing.status == FailureStatus.OPEN
                and existing.occurrence_key == failure.occurrence_key
            ):
                failures[index] = existing.model_copy(
                    update={
                        "occurred_at": failure.occurred_at,
                        "summary": failure.summary,
                        "technical_detail": failure.technical_detail,
                        "repeat_count": existing.repeat_count + 1,
                    }
                )
                return ledger.model_copy(
                    update={"updated_at": failure.occurred_at, "failures": failures}
                )
    failures.append(failure)
    return ledger.model_copy(update={"updated_at": failure.occurred_at, "failures": failures})


def build_failure(
    failure_type: CriticalFailureType,
    *,
    summary: str,
    technical_detail: str = "",
    property_id: str = "",
    property_address: str = "",
    channel: str = "",
    campaign: str = "owner_finance_homes",
    source: str = "",
    buyer_id: str = "",
    now: datetime | None = None,
) -> OperationalFailure:
    occurred_at = now or datetime.now(UTC)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return OperationalFailure(
        failure_type=failure_type,
        occurred_at=occurred_at.astimezone(UTC),
        property_id=property_id,
        property_address=property_address,
        channel=channel,
        campaign=campaign,
        source=source,
        buyer_id=buyer_id,
        summary=summary,
        technical_detail=technical_detail,
        occurrence_key=_occurrence_key(
            failure_type,
            property_id=property_id,
            channel=channel,
            campaign=campaign,
            source=source,
        ),
    )


def record_operational_failure(
    values: Mapping[str, Any],
    failure_type: CriticalFailureType,
    *,
    summary: str,
    technical_detail: str = "",
    property_id: str = "",
    property_address: str = "",
    channel: str = "",
    campaign: str = "owner_finance_homes",
    source: str = "",
    buyer_id: str = "",
    now: datetime | None = None,
) -> OperationalFailureLedger:
    store = OperationalFailureStore(values)
    ledger = store.load()
    updated = append_failure(
        ledger,
        build_failure(
            failure_type,
            summary=summary,
            technical_detail=technical_detail,
            property_id=property_id,
            property_address=property_address,
            channel=channel,
            campaign=campaign,
            source=source,
            buyer_id=buyer_id,
            now=now,
        ),
    )
    store.save(updated)
    return updated


class OperationalFailureStore:
    def __init__(self, values: Mapping[str, Any]) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise OperationalFailureError(
                "Supabase is not configured. Add SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        self._url = settings.url.rstrip("/")
        self._key = settings.service_role_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "apikey": self._key,
            "Content-Type": "application/json",
        }

    def _ensure_bucket(self) -> None:
        request = Request(
            f"{self._url}/storage/v1/bucket/{FAILURE_BUCKET}",
            headers=self._headers,
            method="GET",
        )
        try:
            with urlopen(request, timeout=20):
                return
        except HTTPError as exc:
            if exc.code != 404:
                raise OperationalFailureError(
                    f"Could not inspect the failure-ledger bucket (HTTP {exc.code})."
                ) from exc
        create_request = Request(
            f"{self._url}/storage/v1/bucket",
            data=json.dumps({"id": FAILURE_BUCKET, "name": FAILURE_BUCKET, "public": False}).encode(),
            headers=self._headers,
            method="POST",
        )
        try:
            with urlopen(create_request, timeout=20):
                return
        except HTTPError as exc:
            if exc.code != 409:
                raise OperationalFailureError(
                    f"Could not create the failure-ledger bucket (HTTP {exc.code})."
                ) from exc

    def load(self) -> OperationalFailureLedger:
        self._ensure_bucket()
        request = Request(
            f"{self._url}/storage/v1/object/{FAILURE_BUCKET}/{FAILURE_LEDGER_PATH}",
            headers=self._headers,
            method="GET",
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(FAILURE_MAX_BYTES + 1)
        except HTTPError as exc:
            if exc.code == 404:
                return OperationalFailureLedger()
            raise OperationalFailureError(
                f"Could not read the failure-learning ledger (HTTP {exc.code})."
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise OperationalFailureError("Could not reach the failure-learning ledger.") from exc
        if len(raw) > FAILURE_MAX_BYTES:
            raise OperationalFailureError("Failure-learning ledger is larger than the safe read limit.")
        try:
            return OperationalFailureLedger.model_validate_json(raw)
        except Exception as exc:
            raise OperationalFailureError("Failure-learning ledger contains invalid data.") from exc

    def save(self, ledger: OperationalFailureLedger) -> None:
        self._ensure_bucket()
        body = ledger.model_dump_json().encode()
        if len(body) > FAILURE_MAX_BYTES:
            raise OperationalFailureError("Failure-learning ledger is too large to save safely.")
        request = Request(
            f"{self._url}/storage/v1/object/{FAILURE_BUCKET}/{FAILURE_LEDGER_PATH}",
            data=body,
            headers={**self._headers, "x-upsert": "true"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=20):
                return
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise OperationalFailureError(
                f"Could not save the failure-learning ledger (HTTP {exc.code}). {detail}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise OperationalFailureError("Could not reach the failure-learning ledger while saving.") from exc


def failure_rows(ledger: OperationalFailureLedger) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for failure in sorted(ledger.failures, key=lambda item: item.occurred_at, reverse=True):
        rows.append(
            {
                "Occurred": failure.occurred_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
                "Type": failure.failure_type.value,
                "Status": failure.status.value,
                "Property": failure.property_address or failure.property_id,
                "Channel": failure.channel,
                "Campaign": failure.campaign,
                "Summary": failure.summary,
                "Repeat count": failure.repeat_count,
                "Root cause": failure.root_cause,
                "Resolution": failure.resolution,
                "Prevention note": failure.prevention_note,
            }
        )
    return rows
