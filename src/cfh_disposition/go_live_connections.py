from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .automatic_launch import AutomationDispatchSettings


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    key: str
    name: str
    configured: bool
    required_for: str
    next_step: str


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
            "Add AUTOMATION_WEBHOOK_URL (or MAKE_WEBHOOK_URL) in Streamlit Secrets and connect the receiving Make.com workflow."
            if not automation.configured
            else "Connected. Keep manual-final-post channels human approved.",
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
