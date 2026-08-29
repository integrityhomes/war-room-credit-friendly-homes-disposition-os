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
                    update={"failures": failures, "updated_at": failure.occurred_at}
                )
    return ledger.model_copy(
        update={
            "failures": [*failures, failure],
            "updated_at": failure.occurred_at,
        }
    )


def open_failures(ledger: OperationalFailureLedger) -> list[OperationalFailure]:
    return sorted(
        [item for item in ledger.failures if item.status == FailureStatus.OPEN],
        key=lambda item: item.occurred_at,
        reverse=True,
    )


def close_failure(
    ledger: OperationalFailureLedger,
    *,
    failure_id: str,
    actor: str,
    resolution: str,
    root_cause: str,
    prevention_note: str,
    manual_override: bool = False,
    now: datetime | None = None,
) -> OperationalFailureLedger:
    timestamp = now or datetime.now(UTC)
    found = False
    failures: list[OperationalFailure] = []
    for item in ledger.failures:
        if item.failure_id != failure_id:
            failures.append(item)
            continue
        found = True
        failures.append(
            item.model_copy(
                update={
                    "status": (
                        FailureStatus.MANUAL_OVERRIDE
                        if manual_override
                        else FailureStatus.RESOLVED
                    ),
                    "root_cause": root_cause.strip() or "Unknown",
                    "resolution": resolution.strip(),
                    "prevention_note": prevention_note.strip(),
                    "resolved_at": timestamp,
                    "resolved_by": actor.strip(),
                }
            )
        )
    if not found:
        raise OperationalFailureError("The selected failure could not be found.")
    return ledger.model_copy(update={"failures": failures, "updated_at": timestamp})


class OperationalFailureStore:
    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise OperationalFailureError(
                "Supabase is not configured for the critical failure ledger."
            )
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise OperationalFailureError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(FAILURE_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    FAILURE_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": FAILURE_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise OperationalFailureError(
                    "Could not create the private critical failure bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> OperationalFailureLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(FAILURE_BUCKET).download(FAILURE_LEDGER_PATH)
        except Exception:
            return OperationalFailureLedger()
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return OperationalFailureLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise OperationalFailureError("The critical failure ledger could not be read.") from exc

    def save(self, ledger: OperationalFailureLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > FAILURE_MAX_BYTES:
            raise OperationalFailureError("The critical failure ledger is too large to save.")
        try:
            self._client.storage.from_(FAILURE_BUCKET).upload(
                path=FAILURE_LEDGER_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise OperationalFailureError("Could not save the critical failure ledger.") from exc


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
) -> bool:
    """Best-effort failure logging. Never raise into a buyer-facing workflow."""
    try:
        store = OperationalFailureStore(values)
        ledger = store.load()
        failure = OperationalFailure(
            failure_type=failure_type,
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
        store.save(append_failure(ledger, failure))
        return True
    except OperationalFailureError:
        return False


def render_critical_failure_banner(values: Mapping[str, Any]) -> None:
    """Render open critical failures on the main operating screen with manual override."""
    try:
        store = OperationalFailureStore(values)
        ledger = store.load()
    except OperationalFailureError as exc:
        st.error(f"CRITICAL: Failure monitoring is unavailable — {exc}")
        return

    failures = open_failures(ledger)
    if not failures:
        st.success("Critical failure monitor: no open email, SMS, landing-page, Facebook, lead-capture, or sold-shutdown failures.")
        return

    st.error(f"CRITICAL FAILURES — {len(failures)} open item(s) need attention before they can silently cost leads.")
    for item in failures[:10]:
        label = f"{item.failure_type.value}: {item.summary}"
        if item.repeat_count > 1:
            label += f" — repeated {item.repeat_count} times"
        with st.expander(label, expanded=True):
            if item.property_address:
                st.write(f"**Property:** {item.property_address}")
            if item.channel:
                st.write(f"**Channel:** {item.channel}")
            st.write(f"**Occurred:** {item.occurred_at.astimezone().strftime('%Y-%m-%d %I:%M %p')}")
            actor = st.text_input("Handled by", key=f"failure_actor_{item.failure_id}")
            root_cause = st.text_area("What caused it?", key=f"failure_cause_{item.failure_id}")
            resolution = st.text_area("What did you do to fix or work around it?", key=f"failure_resolution_{item.failure_id}")
            prevention = st.text_area("What should prevent this next time?", key=f"failure_prevention_{item.failure_id}")
            resolved_col, override_col = st.columns(2)
            if resolved_col.button("Mark Fixed", key=f"failure_fixed_{item.failure_id}", use_container_width=True):
                try:
                    updated = close_failure(
                        ledger,
                        failure_id=item.failure_id,
                        actor=actor or "Unknown operator",
                        resolution=resolution or "Fixed and verified manually.",
                        root_cause=root_cause or "Unknown",
                        prevention_note=prevention,
                    )
                    store.save(updated)
                    st.rerun()
                except OperationalFailureError as exc:
                    st.error(str(exc))
            if override_col.button("Manual Override / Continue", key=f"failure_override_{item.failure_id}", use_container_width=True):
                try:
                    updated = close_failure(
                        ledger,
                        failure_id=item.failure_id,
                        actor=actor or "Unknown operator",
                        resolution=resolution or "Manual override used; automated path not verified.",
                        root_cause=root_cause or "Unknown",
                        prevention_note=prevention,
                        manual_override=True,
                    )
                    store.save(updated)
                    st.rerun()
                except OperationalFailureError as exc:
                    st.error(str(exc))
