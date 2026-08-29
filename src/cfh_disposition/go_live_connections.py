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
from .email_handoff import EmailHandoffSettings
from .reactivation_autopilot import ReactivationDispatchSettings
from .rei_blackbook_sms import SmsHandoffSettings
from .social_publish_handoff import SocialPublishSettings

CONNECTION_TEST_EVENT = "credit_friendly_homes.connection.test"
CONNECTION_TEST_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    key: str
    name: str
    configured: bool
    status_label: str
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
    email = EmailHandoffSettings.from_mapping(values)
    sms = SmsHandoffSettings.from_mapping(values)
    reactivation = ReactivationDispatchSettings.from_mapping(values)
    social = SocialPublishSettings.from_mapping(values)
    meta_present = _has(values, "META_AD_ACCOUNT_ID", "META_ACCESS_TOKEN")
    google_present = _has(values, "GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_DEVELOPER_TOKEN")

    return (
        ConnectionStatus(
            "publishing_webhook",
            "General Automation Webhook",
            automation.configured,
            "Handoff configured" if automation.configured else "Needs connection",
            "Legacy/general external campaign automation only; Blog and Market SEO no longer depend on this webhook",
            (
                "Add the approved AUTOMATION_WEBHOOK_URL only if the general external automation workflow is still needed."
                if not automation.configured
                else "Configured. Use the safe webhook test before any external campaign handoff."
            ),
        ),
        ConnectionStatus(
            "email_sender",
            "Email Sender Handoff",
            email.configured,
            "Handoff configured" if email.configured else "Needs connection",
            "Matched Buyer Email",
            (
                "Add the approved HTTPS EMAIL_SENDER_WEBHOOK_URL. Provider credentials remain downstream."
                if not email.configured
                else "Configured. Live use still requires saved buyer email consent and operator confirmation."
            ),
        ),
        ConnectionStatus(
            "sms_sender",
            "REI BlackBook / Profit Dial SMS Handoff",
            sms.configured,
            "Handoff configured" if sms.configured else "Needs connection",
            "Matched Buyer SMS",
            (
                "Add the approved Zapier HTTPS endpoint as SMS_SENDER_WEBHOOK_URL."
                if not sms.configured
                else "Configured. Live use still requires saved SMS consent and operator confirmation."
            ),
        ),
        ConnectionStatus(
            "buyer_reactivation",
            "Buyer Reactivation Outreach",
            reactivation.configured,
            "Handoff configured" if reactivation.configured else "Needs connection",
            "Approved email/SMS reactivation jobs",
            (
                "Add BUYER_OUTREACH_WEBHOOK_URL or the approved reactivation automation endpoint."
                if not reactivation.configured
                else "Configured. Jobs still require approval and a fresh consent/DNC recheck before dispatch."
            ),
        ),
        ConnectionStatus(
            "social_publish",
            "Social Publication Adapter",
            social.configured,
            "Handoff configured" if social.configured else "Optional / manual final post",
            "Instagram, TikTok, and YouTube approved-package handoff",
            (
                "Add SOCIAL_PUBLISH_WEBHOOK_URL only when an approved publication adapter is available; manual final posting remains supported."
                if not social.configured
                else "Configured. Adapter acceptance is a handoff only, not proof that a platform published the post."
            ),
        ),
        ConnectionStatus(
            "meta_ads",
            "Meta Ads Account Details",
            meta_present,
            "Account details present" if meta_present else "Needs account setup",
            "Meta Housing Ads planning-to-launch transition",
            (
                "Add approved Meta account connection details when ready for a separately owner-approved live campaign."
                if not meta_present
                else "Account details are present. This is not launch authority; targeting and spend still require owner approval."
            ),
        ),
        ConnectionStatus(
            "google_ads",
            "Google Ads Account Details",
            google_present,
            "Account details present" if google_present else "Needs account setup",
            "Google Search Ads planning-to-launch transition",
            (
                "Add approved Google Ads connection details when ready for a separately owner-approved live campaign."
                if not google_present
                else "Account details are present. This is not launch authority; keywords, targeting, and spend still require owner approval."
            ),
        ),
    )


def connection_summary(rows: tuple[ConnectionStatus, ...]) -> dict[str, int]:
    return {
        "total": len(rows),
        "configured": sum(row.configured for row in rows),
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
            "General automation webhook is not configured. Add AUTOMATION_WEBHOOK_URL first."
        )
    payload = build_publishing_connection_test_payload(
        requested_by=requested_by,
        now=now,
    )
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
            f"The automation engine rejected the safe test (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("The automation engine could not be reached by the safe test.") from exc
    if not 200 <= status_code < 300:
        raise ValueError(
            f"The automation engine returned HTTP {status_code} during the safe test."
        )
    sent_at = now or datetime.now(UTC)
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return ConnectionTestReceipt(
        status_code=status_code,
        sent_at=sent_at.astimezone(UTC),
        response_text=response_text[:AUTOMATION_RESPONSE_LIMIT],
    )


def automation_connection_sample_json(*, requested_by: str = "Connection Center") -> str:
    return json.dumps(
        build_publishing_connection_test_payload(requested_by=requested_by),
        indent=2,
        sort_keys=True,
    )
