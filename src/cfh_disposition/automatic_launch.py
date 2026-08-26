from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .ai_campaign import CampaignPackage
from .channels import CHANNELS, MarketingChannel
from .models import OwnerFinanceProperty

AUTOMATION_EVENT = "credit_friendly_homes.campaign.approved"
AUTOMATION_SCHEMA_VERSION = "1.4"
AUTOMATION_TIMEOUT_SECONDS = 30
AUTOMATION_RESPONSE_LIMIT = 12_000
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
RESTRICTED_FINAL_POST_CHANNELS = {"marketplace", "facebook_groups", "classifieds", "nextdoor"}
FACEBOOK_MARKETPLACE_NO_LINK_CHANNELS = {"marketplace"}
INTERNAL_LIVE_CHANNELS = {"property_page"}
CONFIRMED_EXTERNAL_STATUSES = {"accepted", "queued", "scheduled", "sent", "published", "posted", "live"}


class AutomationLaunchError(RuntimeError):
    """Raised when an approved campaign cannot be submitted to the publishing workflow."""


class LaunchAction(StrEnum):
    INTERNAL_LIVE = "Live in Disposition OS"
    AUTO_PUBLISH = "Automatic publishing workflow"
    MANUAL_FINAL_POST = "Manual final platform post"


@dataclass(frozen=True, slots=True)
class AutomationDispatchSettings:
    webhook_url: str
    signing_secret: str = ""
    timeout_seconds: int = AUTOMATION_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        parts = urlsplit(self.webhook_url)
        return parts.scheme in {"http", "https"} and bool(parts.netloc)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> AutomationDispatchSettings:
        webhook = values.get("AUTOMATION_WEBHOOK_URL") or values.get("MAKE_WEBHOOK_URL") or ""
        secret = values.get("AUTOMATION_WEBHOOK_SECRET") or values.get("MAKE_WEBHOOK_SECRET") or ""
        return cls(webhook_url=str(webhook).strip(), signing_secret=str(secret).strip())


@dataclass(frozen=True, slots=True)
class AutomationChannelResult:
    channel_key: str
    status: str
    external_id: str = ""


@dataclass(frozen=True, slots=True)
class AutomationDispatchReceipt:
    status_code: int
    sent_at: datetime
    response_text: str = ""
    dispatch_id: str = ""
    channel_results: tuple[AutomationChannelResult, ...] = ()
    awaiting_confirmation: bool = True


def launch_action_for_channel(channel: MarketingChannel) -> LaunchAction:
    if channel.key in INTERNAL_LIVE_CHANNELS:
        return LaunchAction.INTERNAL_LIVE
    if channel.key in RESTRICTED_FINAL_POST_CHANNELS:
        return LaunchAction.MANUAL_FINAL_POST
    return LaunchAction.AUTO_PUBLISH


def _copy_source(package: CampaignPackage, channel_key: str) -> str:
    mapping = {
        "property_page": package.short_description,
        "blog": package.short_description,
        "market_seo": package.short_description,
        "email": f"Subject: {package.email_subject}\n\n{package.email_body}",
        "sms": package.sms_message,
        "reactivation": package.sms_message,
        "marketplace": package.marketplace_description,
        "facebook_groups": package.facebook_group_post,
        "meta_ads": f"{package.headline}\n\n{package.short_description}",
        "google_ads": f"{package.headline}\n\n{package.short_description}",
        "instagram": package.social_caption,
        "tiktok": package.video_script,
        "youtube": package.video_script,
        "classifieds": package.classified_ad,
        "nextdoor": f"{package.headline}\n\n{package.social_caption}",
    }
    try:
        return mapping[channel_key]
    except KeyError as exc:
        raise ValueError(f"Unknown marketing channel: {channel_key}") from exc


def _marketplace_on_platform_copy(source: str) -> str:
    without_urls = URL_PATTERN.sub("", source)
    lines = [line for line in without_urls.splitlines() if "dwelyx" not in line.lower()]
    cleaned = "\n".join(lines).strip()
    cta = "Send us a Facebook Marketplace message for complete purchase terms, property questions, and next steps."
    if cta.lower() not in cleaned.lower():
        cleaned = f"{cleaned}\n\n{cta}" if cleaned else cta
    return cleaned


def channel_copy_with_link(package: CampaignPackage, channel_key: str, tracked_link: str) -> str:
    source = _copy_source(package, channel_key).strip()
    if channel_key in FACEBOOK_MARKETPLACE_NO_LINK_CHANNELS:
        return _marketplace_on_platform_copy(source)
    if URL_PATTERN.search(source):
        return URL_PATTERN.sub(tracked_link, source)
    return f"{source}\n\nCreate or log in to a Dwelyx buyer account: {tracked_link}"


def _property_payload(item: OwnerFinanceProperty) -> dict[str, Any]:
    return {
        "property_id": str(item.property_id), "address": item.address, "city": item.city,
        "state": item.state, "zip_code": item.zip_code, "county": item.county,
        "bedrooms": item.bedrooms, "bathrooms": str(item.bathrooms) if item.bathrooms is not None else None,
        "square_feet": item.square_feet, "acreage": str(item.acreage) if item.acreage is not None else None,
        "total_price": str(item.total_price) if item.total_price is not None else None,
        "down_payment": str(item.down_payment) if item.down_payment is not None else None,
        "monthly_payment": str(item.monthly_payment) if item.monthly_payment is not None else None,
        "condition_summary": item.condition_summary, "repairs_needed": item.repairs_needed,
        "showing_instructions": item.showing_instructions, "public_disclosures": item.public_disclosures,
        "photo_urls": [str(url) for url in item.photo_urls], "video_url": str(item.video_url) if item.video_url else None,
    }


def build_automatic_launch_payload(property_record: OwnerFinanceProperty, package: CampaignPackage,
    links_by_key: Mapping[str, Mapping[str, str]], *, campaign: str, approved_by: str,
    approved_at: datetime | None = None, marketplace_blocked: bool = False,
    marketplace_block_reason: str = "") -> dict[str, Any]:
    timestamp = approved_at or datetime.now(UTC)
    channel_payloads: list[dict[str, Any]] = []
    for channel in CHANNELS:
        row = links_by_key[channel.key]
        tracked_link = str(row["Tracked Dwelyx link"])
        action = launch_action_for_channel(channel)
        marketplace_no_link = channel.key in FACEBOOK_MARKETPLACE_NO_LINK_CHANNELS
        posting_blocked = channel.key == "marketplace" and marketplace_blocked
        channel_payloads.append({
            "channel_key": channel.key, "channel_name": channel.name, "channel_mode": channel.mode.value,
            "launch_action": action.value, "requires_manual_final_post": action == LaunchAction.MANUAL_FINAL_POST,
            "posting_blocked": posting_blocked, "block_reason": marketplace_block_reason if posting_blocked else "",
            "public_external_link_allowed": not marketplace_no_link,
            "tracked_buyer_link": None if marketplace_no_link else tracked_link,
            "copy": "" if posting_blocked else channel_copy_with_link(package, channel.key, tracked_link),
        })
    return {
        "schema_version": AUTOMATION_SCHEMA_VERSION, "event": AUTOMATION_EVENT,
        "approved_at": timestamp.astimezone(UTC).isoformat(), "approved_by": approved_by,
        "campaign": campaign, "property": _property_payload(property_record),
        "buyer_destination": {"purpose": "Dwelyx buyer registration or login only",
            "publish_property_to_dwelyx": False, "property_sync_to_dwelyx": False,
            "facebook_marketplace_direct_link": False, "facebook_groups_direct_link": True,
            "nextdoor_direct_link": True},
        "marketplace_monthly_gate": {"blocked": marketplace_blocked, "reason": marketplace_block_reason},
        "channels": channel_payloads,
        "response_contract": {
            "dispatch_is_asynchronous": True,
            "generic_2xx_means_submitted_not_published": True,
            "require_per_channel_results": True,
            "require_per_channel_results_in_initial_response": False,
            "confirmed_statuses": sorted(CONFIRMED_EXTERNAL_STATUSES),
            "manual_final_post_channels_are_not_auto_completed": True,
        },
    }


def serialize_launch_payload(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")


def sign_launch_payload(body: bytes, signing_secret: str) -> str:
    if not signing_secret:
        return ""
    return "sha256=" + hmac.new(signing_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def expected_automatic_channel_keys(payload: Mapping[str, Any]) -> set[str]:
    return {str(row.get("channel_key", "")).strip() for row in payload.get("channels", [])
            if isinstance(row, Mapping) and not row.get("posting_blocked")
            and row.get("launch_action") == LaunchAction.AUTO_PUBLISH.value and row.get("channel_key")}


def parse_dispatch_response(response_text: str, payload: Mapping[str, Any]) -> tuple[str, tuple[AutomationChannelResult, ...]]:
    """Treat a generic Zapier response as submission; validate explicit CFH confirmations strictly."""
    if not response_text.strip():
        return "", ()
    try:
        response_payload = json.loads(response_text)
    except (TypeError, json.JSONDecodeError):
        return "", ()
    if not isinstance(response_payload, Mapping):
        return "", ()
    dispatch_id = str(response_payload.get("dispatch_id", "")).strip()
    if response_payload.get("accepted") is not True:
        return dispatch_id, ()
    raw_results = response_payload.get("channel_results")
    if not isinstance(raw_results, list):
        raise AutomationLaunchError("The publishing workflow explicitly accepted the campaign but did not return per-channel results.")
    expected = expected_automatic_channel_keys(payload)
    confirmed: dict[str, AutomationChannelResult] = {}
    for raw in raw_results:
        if not isinstance(raw, Mapping):
            continue
        key = str(raw.get("channel_key", "")).strip()
        status = str(raw.get("status", "")).strip().lower()
        if key in expected and key not in confirmed and status in CONFIRMED_EXTERNAL_STATUSES:
            confirmed[key] = AutomationChannelResult(key, status, str(raw.get("external_id", "")).strip())
    missing = sorted(expected - set(confirmed))
    if missing:
        raise AutomationLaunchError("The publishing workflow did not confirm every automatic channel. Missing: " + ", ".join(missing))
    return dispatch_id, tuple(confirmed[key] for key in sorted(confirmed))


def dispatch_automatic_launch(payload: Mapping[str, Any], settings: AutomationDispatchSettings) -> AutomationDispatchReceipt:
    if not settings.configured:
        raise AutomationLaunchError("Automatic publishing is not connected. Add AUTOMATION_WEBHOOK_URL in Streamlit Secrets.")
    body = serialize_launch_payload(payload)
    headers = {"Content-Type": "application/json", "User-Agent": "Credit-Friendly-Homes-Disposition-OS/1.0",
               "X-CFH-Event": AUTOMATION_EVENT}
    signature = sign_launch_payload(body, settings.signing_secret)
    if signature:
        headers["X-CFH-Signature"] = signature
    request = Request(settings.webhook_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=settings.timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")[:AUTOMATION_RESPONSE_LIMIT]
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:AUTOMATION_RESPONSE_LIMIT]
        raise AutomationLaunchError(f"The automatic publishing workflow rejected the campaign (HTTP {exc.code}). {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise AutomationLaunchError("The automatic publishing workflow could not be reached. No external channel was marked launched.") from exc
    if not 200 <= status_code < 300:
        raise AutomationLaunchError(f"The automatic publishing workflow returned HTTP {status_code}. No external channel was marked launched.")
    dispatch_id, channel_results = parse_dispatch_response(response_text, payload)
    return AutomationDispatchReceipt(status_code=status_code, sent_at=datetime.now(UTC), response_text=response_text,
                                     dispatch_id=dispatch_id, channel_results=channel_results, awaiting_confirmation=True)


def automation_plan_rows() -> list[dict[str, str]]:
    rows = []
    for channel in CHANNELS:
        action = launch_action_for_channel(channel)
        if action == LaunchAction.INTERNAL_LIVE:
            result = "The property landing page is live in this app when the property passes validation."
        elif channel.key == "marketplace":
            result = "A no-link package is prepared for a final human post, subject to the five-per-month Homes for Sale or Rent safety gate."
        elif channel.key == "nextdoor":
            result = "A tracked Business Post and paid housing-ad package is prepared. Business Page verification, final publication, platform review, targeting review, and ad spending remain manual."
        elif action == LaunchAction.MANUAL_FINAL_POST:
            result = "The complete package, including the tracked Dwelyx link where allowed, is delivered for a final human post."
        else:
            result = "The approved package is submitted to the connected publishing workflow. Submission is not counted as publication; the channel remains awaiting confirmation until a confirmed result is recorded."
        rows.append({"Channel": channel.name, "Launch action": action.value, "What happens": result})
    return rows
