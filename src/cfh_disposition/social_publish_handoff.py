from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import OwnerFinanceProperty
from .social_video_channels import SocialVideoPackage

SOCIAL_PUBLISH_EVENT = "credit_friendly_homes.social_video.approved_publish_handoff"
SOCIAL_PUBLISH_SCHEMA_VERSION = "1.0"
SOCIAL_PUBLISH_TIMEOUT_SECONDS = 20
SOCIAL_PUBLISH_RESPONSE_LIMIT = 2000
SUPPORTED_SOCIAL_CHANNELS = {"instagram", "tiktok", "youtube"}


class SocialPublishHandoffError(RuntimeError):
    """Raised when an approved social package cannot be handed to the publish adapter safely."""


@dataclass(frozen=True, slots=True)
class SocialPublishSettings:
    webhook_url: str = ""

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SocialPublishSettings:
        return cls(webhook_url=str(values.get("SOCIAL_PUBLISH_WEBHOOK_URL", "")).strip())

    @property
    def configured(self) -> bool:
        return self.webhook_url.startswith("https://")


@dataclass(frozen=True, slots=True)
class SocialPublishHandoffReceipt:
    status_code: int
    accepted_at: datetime
    response_text: str = ""


def _normalize_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _idempotency_key(
    *,
    property_id: str,
    campaign: str,
    package: SocialVideoPackage,
    caption: str,
) -> str:
    source = "|".join(
        [
            property_id,
            campaign.strip().casefold(),
            package.channel_key,
            package.post_title,
            caption,
            package.tracked_link,
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_social_publish_payload(
    *,
    property_record: OwnerFinanceProperty,
    package: SocialVideoPackage,
    campaign: str,
    caption: str,
    approved_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if package.channel_key not in SUPPORTED_SOCIAL_CHANNELS:
        raise SocialPublishHandoffError(
            f"Unsupported social publication channel: {package.channel_key}."
        )
    clean_caption = caption.strip()
    if not clean_caption:
        raise SocialPublishHandoffError("The approved social caption is empty.")
    if clean_caption not in package.caption_variants:
        raise SocialPublishHandoffError(
            "The selected caption does not match one of the fact-locked package variations."
        )
    if not package.tracked_link.strip():
        raise SocialPublishHandoffError("The tracked Dwelyx link is missing.")

    timestamp = _normalize_now(now)
    property_id = str(property_record.property_id)
    clean_campaign = campaign.strip() or "owner_finance_homes"
    clean_approver = approved_by.strip()
    if not clean_approver:
        raise SocialPublishHandoffError("The approving operator is required.")

    return {
        "schema_version": SOCIAL_PUBLISH_SCHEMA_VERSION,
        "event": SOCIAL_PUBLISH_EVENT,
        "idempotency_key": _idempotency_key(
            property_id=property_id,
            campaign=clean_campaign,
            package=package,
            caption=clean_caption,
        ),
        "approved_at": timestamp.isoformat(),
        "approved_by": clean_approver,
        "action": "handoff_exact_approved_social_package",
        "channel": package.channel_key,
        "property": {
            "property_id": property_id,
            "address": property_record.display_address,
            "city": property_record.city,
            "state": property_record.state,
        },
        "marketing": {
            "campaign": clean_campaign,
            "title": package.post_title,
            "caption": clean_caption,
            "hashtags": list(package.hashtags),
            "short_script": package.short_script,
            "on_screen_text": list(package.on_screen_text),
            "shot_list": list(package.shot_list),
            "tracked_dwelyx_link": package.tracked_link,
            "call_to_action": package.call_to_action,
        },
        "publication": {
            "destination": package.channel_name,
            "adapter_must_confirm_platform_acceptance": True,
            "cfh_handoff_is_not_proof_of_publication": True,
            "media_upload_or_selection_required_downstream": True,
        },
        "compliance": {
            "operator_approval_required": True,
            "do_not_change_title_or_caption": True,
            "do_not_invent_property_facts": True,
            "approval_promises_allowed": False,
            "tracked_link_must_be_preserved_when_platform_allows": True,
        },
    }


def dispatch_social_publish_handoff(
    values: Mapping[str, Any],
    *,
    property_record: OwnerFinanceProperty,
    package: SocialVideoPackage,
    campaign: str,
    caption: str,
    approved_by: str,
) -> SocialPublishHandoffReceipt:
    settings = SocialPublishSettings.from_mapping(values)
    if not settings.configured:
        raise SocialPublishHandoffError(
            "Social publication is not connected. Add the approved HTTPS adapter as SOCIAL_PUBLISH_WEBHOOK_URL in Streamlit Secrets."
        )

    payload = build_social_publish_payload(
        property_record=property_record,
        package=package,
        campaign=campaign,
        caption=caption,
        approved_by=approved_by,
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = Request(
        settings.webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Credit-Friendly-Homes-Social-Publish/1.0",
            "X-CFH-Event": SOCIAL_PUBLISH_EVENT,
            "X-CFH-Idempotency-Key": payload["idempotency_key"],
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=SOCIAL_PUBLISH_TIMEOUT_SECONDS) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:SOCIAL_PUBLISH_RESPONSE_LIMIT]
        raise SocialPublishHandoffError(
            f"The social publication adapter rejected the handoff (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise SocialPublishHandoffError(
            "The configured social publication adapter could not be reached."
        ) from exc

    if not 200 <= status_code < 300:
        raise SocialPublishHandoffError(
            f"The social publication adapter returned HTTP {status_code}."
        )

    return SocialPublishHandoffReceipt(
        status_code=status_code,
        accepted_at=datetime.now(UTC),
        response_text=response_text[:SOCIAL_PUBLISH_RESPONSE_LIMIT],
    )
