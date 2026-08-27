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

SAFE_FULL_PAYLOAD_TEST_EVENT = "credit_friendly_homes.campaign.full_payload_test"


@dataclass(frozen=True, slots=True)
class SafePayloadTestReceipt:
    status_code: int
    sent_at: datetime
    response_text: str = ""


def build_safe_full_payload_test_payload(
    full_campaign_payload: Mapping[str, Any],
    *,
    requested_by: str,
    requested_at: datetime | None = None,
) -> dict[str, Any]:
    """Wrap a real campaign payload so Zapier can inspect it without executing channels.

    The live Zap loops over the top-level ``channels`` collection. This test deliberately
    leaves that collection empty and places the complete real payload under
    ``full_campaign_payload`` for inspection. That gives Zapier the entire property and
    15-channel package while providing no executable channel rows to downstream steps.
    """
    timestamp = requested_at or datetime.now(UTC)
    return {
        "schema_version": str(full_campaign_payload.get("schema_version", "")),
        "event": SAFE_FULL_PAYLOAD_TEST_EVENT,
        "test_mode": True,
        "execution_allowed": False,
        "external_actions_allowed": False,
        "send_email": False,
        "send_sms": False,
        "publish_social": False,
        "publish_ads": False,
        "spend_money": False,
        "requested_by": requested_by.strip() or "team",
        "requested_at": timestamp.astimezone(UTC).isoformat(),
        # Deliberately empty. Existing live Zap loops have nothing executable to process.
        "channels": [],
        # Complete real launch package remains available for Zapier inspection/mapping.
        "full_campaign_payload": dict(full_campaign_payload),
        "safety": {
            "purpose": "Validate the complete CFH-to-Zapier payload only",
            "must_not_publish": True,
            "must_not_send_email": True,
            "must_not_send_sms": True,
            "must_not_start_ads": True,
            "must_not_spend_money": True,
            "top_level_channel_count": 0,
            "full_payload_channel_count": len(full_campaign_payload.get("channels", [])),
        },
    }


def dispatch_safe_full_payload_test(
    payload: Mapping[str, Any],
    settings: AutomationDispatchSettings,
) -> SafePayloadTestReceipt:
    if not settings.configured:
        raise ValueError(
            "Automatic publishing is not connected. Add AUTOMATION_WEBHOOK_URL in Streamlit Secrets."
        )
    if payload.get("event") != SAFE_FULL_PAYLOAD_TEST_EVENT:
        raise ValueError("Refusing to send a payload that is not the safe full-payload test event.")
    if payload.get("execution_allowed") is not False or payload.get("channels") != []:
        raise ValueError("Refusing to send a full-payload test with executable top-level channels.")

    body = serialize_launch_payload(payload)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Credit-Friendly-Homes-Disposition-OS/1.0",
        "X-CFH-Event": SAFE_FULL_PAYLOAD_TEST_EVENT,
        "X-CFH-Test-Mode": "true",
        "X-CFH-Execution-Allowed": "false",
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
            response_text = response.read().decode("utf-8", errors="replace")[
                :AUTOMATION_RESPONSE_LIMIT
            ]
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:AUTOMATION_RESPONSE_LIMIT]
        raise ValueError(
            f"Zapier rejected the safe full-payload test (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ValueError("Zapier could not be reached for the safe full-payload test.") from exc

    if not 200 <= status_code < 300:
        raise ValueError(f"Zapier returned HTTP {status_code} for the safe full-payload test.")

    return SafePayloadTestReceipt(
        status_code=status_code,
        sent_at=datetime.now(UTC),
        response_text=response_text,
    )


def safe_payload_sample_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)
