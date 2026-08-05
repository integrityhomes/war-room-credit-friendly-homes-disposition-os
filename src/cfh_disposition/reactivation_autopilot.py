from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .buyer_intent import BuyerIntentLedger, BuyerPropertyMatch, IntentTier, OutreachChannel
from .storage import SupabaseSettings

AUTOPILOT_BUCKET = "cfh-reactivation-autopilot"
AUTOPILOT_PATH = "reactivation-autopilot/ledger.json"
AUTOPILOT_MAX_BYTES = 2 * 1024 * 1024
AUTOPILOT_EVENT = "credit_friendly_homes.buyer_outreach.approved"
AUTOPILOT_SCHEMA_VERSION = "1.0"
AUTOPILOT_TIMEOUT_SECONDS = 30
AUTOPILOT_RESPONSE_LIMIT = 500
MAX_JOBS_PER_BUILD = 500
STOP_SIGNAL_TYPES = {
    "reply",
    "application_started",
    "showing_requested",
    "call_connected",
}


class ReactivationAutopilotError(RuntimeError):
    """Raised when a buyer-reactivation automation step cannot be completed."""


class ReactivationJobStatus(StrEnum):
    QUEUED = "Queued"
    APPROVED = "Approved"
    DISPATCHED = "Dispatched"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    STOPPED = "Stopped by Engagement"


class ReactivationJob(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    buyer_id: str
    buyer_name: str
    property_id: str
    property_address: str
    channel: OutreachChannel
    recipient: str
    subject: str = ""
    message: str
    tracked_link: str
    score: int = Field(ge=0, le=100)
    tier: IntentTier
    scheduled_for: datetime
    sequence_step: int = Field(ge=1, le=10)
    sequence_label: str
    status: ReactivationJobStatus = ReactivationJobStatus.QUEUED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    approved_at: datetime | None = None
    approved_by: str = ""
    dispatched_at: datetime | None = None
    dispatch_attempts: int = Field(default=0, ge=0)
    external_response: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=1000)


class ReactivationAutopilotLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    jobs: list[ReactivationJob] = Field(default_factory=list)


class ReactivationDispatchSettings(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    webhook_url: str = ""
    signing_secret: str = ""
    timeout_seconds: int = AUTOPILOT_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return self.webhook_url.startswith(("https://", "http://"))

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> ReactivationDispatchSettings:
        webhook = (
            values.get("BUYER_OUTREACH_WEBHOOK_URL")
            or values.get("REACTIVATION_WEBHOOK_URL")
            or values.get("AUTOMATION_WEBHOOK_URL")
            or values.get("MAKE_WEBHOOK_URL")
            or ""
        )
        secret = (
            values.get("BUYER_OUTREACH_WEBHOOK_SECRET")
            or values.get("REACTIVATION_WEBHOOK_SECRET")
            or values.get("AUTOMATION_WEBHOOK_SECRET")
            or values.get("MAKE_WEBHOOK_SECRET")
            or ""
        )
        return cls(webhook_url=str(webhook).strip(), signing_secret=str(secret).strip())


class ReactivationDispatchReceipt(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status_code: int
    dispatched_at: datetime
    response_text: str = ""


def _normalize_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    return current.replace(tzinfo=UTC) if current.tzinfo is None else current.astimezone(UTC)


def _job_key(buyer_id: str, property_id: str, channel: OutreachChannel, sequence_step: int) -> tuple[str, str, str, int]:
    return buyer_id, property_id, channel.value, sequence_step


def sequence_plan(match: BuyerPropertyMatch, *, now: datetime | None = None) -> list[tuple[OutreachChannel, datetime, str]]:
    current = _normalize_now(now)
    plan: list[tuple[OutreachChannel, datetime, str]] = []
    if match.tier == IntentTier.HOT:
        if match.sms_allowed:
            plan.append((OutreachChannel.SMS, current, "Hot buyer: immediate SMS"))
        if match.email_allowed:
            plan.append((OutreachChannel.EMAIL, current + timedelta(days=1), "Hot buyer: email follow-up after 24 hours"))
    elif match.tier == IntentTier.WARM:
        if match.email_allowed:
            plan.append((OutreachChannel.EMAIL, current, "Warm buyer: email first"))
        if match.sms_allowed:
            plan.append((OutreachChannel.SMS, current + timedelta(days=2), "Warm buyer: SMS follow-up after 48 hours"))
    else:
        if match.email_allowed:
            plan.append((OutreachChannel.EMAIL, current, "Nurture buyer: email only"))
        elif match.sms_allowed:
            plan.append((OutreachChannel.SMS, current, "Nurture buyer: consented SMS"))
    return plan


def build_reactivation_jobs(
    ledger: ReactivationAutopilotLedger,
    matches: Sequence[BuyerPropertyMatch],
    *,
    now: datetime | None = None,
    max_jobs: int = MAX_JOBS_PER_BUILD,
) -> tuple[ReactivationAutopilotLedger, int, int]:
    current = _normalize_now(now)
    existing_keys = {
        _job_key(job.buyer_id, job.property_id, job.channel, job.sequence_step)
        for job in ledger.jobs
        if job.status not in {ReactivationJobStatus.CANCELLED, ReactivationJobStatus.FAILED}
    }
    jobs = list(ledger.jobs)
    created = 0
    skipped = 0

    for match in matches:
        for step, (channel, scheduled_for, label) in enumerate(sequence_plan(match, now=current), start=1):
            if created >= max_jobs:
                skipped += 1
                continue
            key = _job_key(match.buyer_id, match.property_id, channel, step)
            if key in existing_keys:
                skipped += 1
                continue
            recipient = match.email if channel == OutreachChannel.EMAIL else match.phone
            subject = match.email_subject if channel == OutreachChannel.EMAIL else ""
            message = match.email_body if channel == OutreachChannel.EMAIL else match.sms_message
            jobs.append(
                ReactivationJob(
                    buyer_id=match.buyer_id,
                    buyer_name=match.buyer_name,
                    property_id=match.property_id,
                    property_address=match.property_address,
                    channel=channel,
                    recipient=recipient,
                    subject=subject,
                    message=message,
                    tracked_link=match.tracked_link,
                    score=match.score,
                    tier=match.tier,
                    scheduled_for=scheduled_for,
                    sequence_step=step,
                    sequence_label=label,
                    created_at=current,
                )
            )
            existing_keys.add(key)
            created += 1

    updated = ledger.model_copy(update={"jobs": jobs, "updated_at": current})
    return updated, created, skipped


def _replace_job(ledger: ReactivationAutopilotLedger, replacement: ReactivationJob, *, now: datetime | None = None) -> ReactivationAutopilotLedger:
    current = _normalize_now(now)
    found = False
    jobs: list[ReactivationJob] = []
    for job in ledger.jobs:
        if job.job_id == replacement.job_id:
            jobs.append(replacement)
            found = True
        else:
            jobs.append(job)
    if not found:
        raise ReactivationAutopilotError("The selected reactivation job could not be found.")
    return ledger.model_copy(update={"jobs": jobs, "updated_at": current})


def approve_job(
    ledger: ReactivationAutopilotLedger,
    *,
    job_id: str,
    approved_by: str,
    notes: str = "",
    now: datetime | None = None,
) -> ReactivationAutopilotLedger:
    current = _normalize_now(now)
    job = next((item for item in ledger.jobs if item.job_id == job_id), None)
    if not job:
        raise ReactivationAutopilotError("The selected reactivation job could not be found.")
    if job.status not in {ReactivationJobStatus.QUEUED, ReactivationJobStatus.FAILED}:
        raise ReactivationAutopilotError(f"Only queued or failed jobs can be approved. Current status: {job.status.value}.")
    replacement = job.model_copy(
        update={
            "status": ReactivationJobStatus.APPROVED,
            "approved_at": current,
            "approved_by": approved_by,
            "notes": notes,
            "external_response": "",
        }
    )
    return _replace_job(ledger, replacement, now=current)


def cancel_job(
    ledger: ReactivationAutopilotLedger,
    *,
    job_id: str,
    notes: str = "",
    now: datetime | None = None,
) -> ReactivationAutopilotLedger:
    current = _normalize_now(now)
    job = next((item for item in ledger.jobs if item.job_id == job_id), None)
    if not job:
        raise ReactivationAutopilotError("The selected reactivation job could not be found.")
    if job.status == ReactivationJobStatus.DISPATCHED:
        raise ReactivationAutopilotError("A dispatched job cannot be cancelled.")
    replacement = job.model_copy(update={"status": ReactivationJobStatus.CANCELLED, "notes": notes})
    return _replace_job(ledger, replacement, now=current)


def engagement_stop_reason(
    intent_ledger: BuyerIntentLedger,
    job: ReactivationJob,
) -> str:
    relevant = [
        signal
        for signal in intent_ledger.signals
        if signal.buyer_id == job.buyer_id
        and signal.signal_type.casefold() in STOP_SIGNAL_TYPES
        and signal.occurred_at >= job.created_at
        and (not signal.property_id or signal.property_id == job.property_id)
    ]
    if not relevant:
        return ""
    latest = max(relevant, key=lambda item: item.occurred_at)
    return f"Stopped because {latest.signal_type.replace('_', ' ')} was recorded after the sequence started."


def stop_job_for_engagement(
    ledger: ReactivationAutopilotLedger,
    *,
    job_id: str,
    reason: str,
    now: datetime | None = None,
) -> ReactivationAutopilotLedger:
    current = _normalize_now(now)
    job = next((item for item in ledger.jobs if item.job_id == job_id), None)
    if not job:
        raise ReactivationAutopilotError("The selected reactivation job could not be found.")
    if job.status == ReactivationJobStatus.DISPATCHED:
        return ledger
    replacement = job.model_copy(update={"status": ReactivationJobStatus.STOPPED, "notes": reason})
    return _replace_job(ledger, replacement, now=current)


def due_jobs(
    ledger: ReactivationAutopilotLedger,
    *,
    now: datetime | None = None,
    statuses: set[ReactivationJobStatus] | None = None,
) -> list[ReactivationJob]:
    current = _normalize_now(now)
    allowed = statuses or {ReactivationJobStatus.QUEUED, ReactivationJobStatus.APPROVED, ReactivationJobStatus.FAILED}
    return sorted(
        [job for job in ledger.jobs if job.status in allowed and job.scheduled_for <= current],
        key=lambda job: (-job.score, job.scheduled_for, job.buyer_name.casefold()),
    )


def build_dispatch_payload(job: ReactivationJob) -> dict[str, Any]:
    return {
        "schema_version": AUTOPILOT_SCHEMA_VERSION,
        "event": AUTOPILOT_EVENT,
        "idempotency_key": job.job_id,
        "approved_at": job.approved_at.astimezone(UTC).isoformat() if job.approved_at else None,
        "approved_by": job.approved_by,
        "channel": job.channel.value.lower(),
        "recipient": job.recipient,
        "subject": job.subject or None,
        "message": job.message,
        "buyer": {"buyer_id": job.buyer_id, "name": job.buyer_name},
        "property": {"property_id": job.property_id, "address": job.property_address},
        "intent": {"score": job.score, "tier": job.tier.value},
        "sequence": {
            "step": job.sequence_step,
            "label": job.sequence_label,
            "scheduled_for": job.scheduled_for.astimezone(UTC).isoformat(),
        },
        "tracked_dwelyx_link": job.tracked_link,
        "compliance": {
            "consent_required": True,
            "do_not_contact_blocked": True,
            "approval_promises_allowed": False,
            "opt_out_language_included": True,
            "equal_housing_language_included": True,
        },
    }


def _serialized_payload(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


def _signature(body: bytes, signing_secret: str) -> str:
    if not signing_secret:
        return ""
    return "sha256=" + hmac.new(signing_secret.encode(), body, hashlib.sha256).hexdigest()


def dispatch_job(job: ReactivationJob, settings: ReactivationDispatchSettings) -> ReactivationDispatchReceipt:
    if not settings.configured:
        raise ReactivationAutopilotError(
            "Buyer outreach automation is not connected. Add BUYER_OUTREACH_WEBHOOK_URL or AUTOMATION_WEBHOOK_URL in Streamlit Secrets."
        )
    if job.status != ReactivationJobStatus.APPROVED:
        raise ReactivationAutopilotError("The job must be approved before it can be dispatched.")
    current = _normalize_now()
    if job.scheduled_for > current:
        raise ReactivationAutopilotError("This approved job is scheduled for a future time.")

    body = _serialized_payload(build_dispatch_payload(job))
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Credit-Friendly-Homes-Buyer-Reactivation/1.0",
        "X-CFH-Event": AUTOPILOT_EVENT,
        "X-CFH-Idempotency-Key": job.job_id,
    }
    signature = _signature(body, settings.signing_secret)
    if signature:
        headers["X-CFH-Signature"] = signature
    request = Request(settings.webhook_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=settings.timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode(errors="replace")[:AUTOPILOT_RESPONSE_LIMIT]
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:AUTOPILOT_RESPONSE_LIMIT]
        raise ReactivationAutopilotError(f"The outreach workflow rejected the job (HTTP {exc.code}). {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise ReactivationAutopilotError("The outreach workflow could not be reached. The job was not marked dispatched.") from exc
    if not 200 <= status_code < 300:
        raise ReactivationAutopilotError(f"The outreach workflow returned HTTP {status_code}. The job was not marked dispatched.")
    return ReactivationDispatchReceipt(status_code=status_code, dispatched_at=_normalize_now(), response_text=response_text)


def record_dispatch_success(
    ledger: ReactivationAutopilotLedger,
    *,
    job_id: str,
    receipt: ReactivationDispatchReceipt,
) -> ReactivationAutopilotLedger:
    job = next((item for item in ledger.jobs if item.job_id == job_id), None)
    if not job:
        raise ReactivationAutopilotError("The selected reactivation job could not be found.")
    replacement = job.model_copy(
        update={
            "status": ReactivationJobStatus.DISPATCHED,
            "dispatched_at": receipt.dispatched_at,
            "dispatch_attempts": job.dispatch_attempts + 1,
            "external_response": receipt.response_text,
        }
    )
    return _replace_job(ledger, replacement, now=receipt.dispatched_at)


def record_dispatch_failure(
    ledger: ReactivationAutopilotLedger,
    *,
    job_id: str,
    error: str,
    now: datetime | None = None,
) -> ReactivationAutopilotLedger:
    current = _normalize_now(now)
    job = next((item for item in ledger.jobs if item.job_id == job_id), None)
    if not job:
        raise ReactivationAutopilotError("The selected reactivation job could not be found.")
    replacement = job.model_copy(
        update={
            "status": ReactivationJobStatus.FAILED,
            "dispatch_attempts": job.dispatch_attempts + 1,
            "external_response": error[:500],
        }
    )
    return _replace_job(ledger, replacement, now=current)


def job_rows(ledger: ReactivationAutopilotLedger) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for job in sorted(ledger.jobs, key=lambda item: (item.scheduled_for, -item.score)):
        rows.append(
            {
                "Status": job.status.value,
                "Due": job.scheduled_for.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Intent": job.tier.value,
                "Score": job.score,
                "Buyer": job.buyer_name,
                "Property": job.property_address,
                "Channel": job.channel.value,
                "Sequence": job.sequence_label,
                "Attempts": job.dispatch_attempts,
            }
        )
    return rows


class ReactivationAutopilotStore:
    """Private Supabase Storage ledger for buyer-reactivation automation jobs."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise ReactivationAutopilotError("Supabase is not configured for buyer-reactivation automation.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise ReactivationAutopilotError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(AUTOPILOT_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    AUTOPILOT_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": AUTOPILOT_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise ReactivationAutopilotError("Could not create the private buyer-reactivation automation bucket.") from exc
        self._bucket_ready = True

    def load(self) -> ReactivationAutopilotLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(AUTOPILOT_BUCKET).download(AUTOPILOT_PATH)
        except Exception:
            return ReactivationAutopilotLedger()
        try:
            payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
            return ReactivationAutopilotLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ReactivationAutopilotError("The saved buyer-reactivation automation queue could not be read.") from exc

    def save(self, ledger: ReactivationAutopilotLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > AUTOPILOT_MAX_BYTES:
            raise ReactivationAutopilotError("The buyer-reactivation automation queue is too large to save.")
        try:
            self._client.storage.from_(AUTOPILOT_BUCKET).upload(
                path=AUTOPILOT_PATH,
                file=payload,
                file_options={"content-type": "application/json", "cache-control": "0", "upsert": "true"},
            )
        except Exception as exc:
            raise ReactivationAutopilotError("Could not save the buyer-reactivation automation queue.") from exc
