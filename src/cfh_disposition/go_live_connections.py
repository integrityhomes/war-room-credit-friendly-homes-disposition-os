from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .automatic_launch import (
    AUTOMATION_RESPONSE_LIMIT,
    AUTOMATION_TIMEOUT_SECONDS,
    AutomationDispatchSettings,
    serialize_launch_payload,
    sign_launch_payload,
)

CONNECTION_TEST_EVENT = "credit_friendly_homes.connection.test"
CONNECTION_TEST_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    key: str
    name: str
    configured: bool
    required_for: str
    next_step: str


@dataclass(frozen=True, slots=True)
class ConnectionTestReceipt:
    status_code: int
    sent_at: datetime
    response_text: str = ""


def _has(values: Mapping[str, Any], *keys: str) -> bool:
    return any(str(values.get(key, "")).strip() for key in keys)


def build_connection_status(values: Mapping[str, Any]) -> tuple[ConnectionStatus, ...]:
    automation = AutomationDispatchSettings.from_mapping(values)
    rows = (
        ConnectionStatus(
            "publishing_webhook",
            "15-Channel Publishing Workflow",
            automation.configured,
            "Blog, Market SEO, Email/SMS handoff, paid/social publishing workflows",
            (
                "Add AUTOMATION_WEBHOOK_URL (or MAKE_WEBHOOK_URL) in Streamlit Secrets "
                "and connect the receiving Make.com workflow."
            )
            if not automation.configured
            else "Connected. Run the safe webhook test before any live campaign dispatch.",
        ),
        ConnectionStatus(
            "email_sender",
            "Email Sender",
            _has(values, "EMAIL_SENDER_WEBHOOK_URL", "EMAIL_PROVIDER_API_KEY"),
            "Matched Buyer Email and email reactivation",
            "Connect the approved email sender before live sending."
            if not _has(values, "EMAIL_SENDER_WEBHOOK_URL", "EMAIL_PROVIDER_API_KEY")
            else "Connected. Continue enforcing saved email consent and unsubscribe status.",
        ),
        ConnectionStatus(
            "sms_sender",
            "SMS Sender",
            _has(values, "SMS_SENDER_WEBHOOK_URL", "SMS_PROVIDER_API_KEY"),
            "Matched Buyer SMS and SMS reactivation",
            "Connect the approved SMS sender before live sending."
            if not _has(values, "SMS_SENDER_WEBHOOK_URL", "SMS_PROVIDER_API_KEY")
            else "Connected. Continue enforcing saved SMS consent and STOP/do-not-contact status.",
        ),
        ConnectionStatus(
            "meta_ads",
            "Meta Ads Account",
            _has(values, "META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN"),
            "Meta Housing Ads",
            "Add the approved Meta ad-account connection when ready for live paid campaigns."
            if not _has(values, "META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN")
            else "Connection details present. Final campaign targeting and spend still require approval.",
        ),
        ConnectionStatus(
            "google_ads",
            "Google Ads Account",
            _has(values, "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_DEVELOPER_TOKEN"),
            "Google Search Ads",
            "Add the approved Google Ads connection when ready for live paid campaigns."
            if not _has(values, "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_DEVELOPER_TOKEN")
            else "Connection details present. Final keywords, negatives, and spend still require approval.",
        ),
    )
    return rows


def connection_summary(rows: tuple[ConnectionStatus, ...]) -> dict[str, int]:
    return {
        "total": len(rows),
        "connected": sum(row.configured for row in rows),
        "remaining": sum(not row.configured for row in rows),
    }


def build_publishing_connection_test_payload(
    *,
    requested_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return {
        "schema_version": CONNECTION_TEST_SCHEMA_VERSION,
        "event": CONNECTION_TEST_EVENT,
        "sent_at": timestamp.astimezone(UTC).isoformat(),
        "requested_by": requested_by.strip() or "Connection Center",
        "test_only": True,
        "instructions": (
            "Connection test only. Do not publish, send messages, create ads, or spend money."
        ),
    }


def dispatch_publishing_connection_test(
    values: Mapping[str, Any],
    *,
    requested_by: str,
    now: datetime | None = None,
) -> ConnectionTestReceipt:
    settings = AutomationDispatchSettings.from_mapping(values)
    if not settings.configured:
        raise ValueError(
            "Publishing webhook is not configured. Add AUTOMATION_WEBHOOK_URL or MAKE_WEBHOOK_URL first."
        )

    payload = build_publishing_connection_test_payload(requested_by=requested_by, now=now)
    body = serialize_launch_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Credit-Friendly-Homes-Disposition-OS/1.0",
        "X-CFH-Event": CONNECTION_TEST_EVENT,
    }
    signature = sign_launch_payload(body, settings.signing_secret)
    if signature:
        headers["X-CFH-Signature"] = signature

    request = Request(settings.webhook_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(
            request,
            timeout=settings.timeout_seconds or AUTOMATION_TIMEOUT_SECONDS,
        ) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:AUTOMATION_RESPONSE_LIMIT]
        raise ValueError(
            f"The publishing workflow rejected the safe test (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("The publishing workflow could not be reached by the safe test.") from exc

    if not 200 <= status_code < 300:
        raise ValueError(f"The publishing workflow returned HTTP {status_code} during the safe test.")

    sent_at = now or datetime.now(UTC)
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return ConnectionTestReceipt(
        status_code=status_code,
        sent_at=sent_at.astimezone(UTC),
        response_text=response_text[:AUTOMATION_RESPONSE_LIMIT],
    )


def make_connection_sample_json(*, requested_by: str = "Connection Center") -> str:
    payload = build_publishing_connection_test_payload(requested_by=requested_by)
    return json.dumps(payload, indent=2, sort_keys=True)
