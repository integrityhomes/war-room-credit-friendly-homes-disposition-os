from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import BuyerProfile, OwnerFinanceProperty

EMAIL_HANDOFF_TIMEOUT_SECONDS = 15
EMAIL_HANDOFF_RESPONSE_LIMIT = 2000
EMAIL_HANDOFF_EVENT = "credit_friendly_homes.marketing.email_handoff"
EMAIL_HANDOFF_SCHEMA_VERSION = "1.0"


class EmailHandoffError(RuntimeError):
    """Raised when CFH cannot safely hand an approved email to the configured sender."""


@dataclass(frozen=True, slots=True)
class EmailHandoffSettings:
    webhook_url: str = ""

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> EmailHandoffSettings:
        # The downstream automation owns provider credentials. CFH only stores the
        # approved HTTPS handoff endpoint, matching the existing SMS architecture.
        return cls(webhook_url=str(values.get("EMAIL_SENDER_WEBHOOK_URL", "")).strip())

    @property
    def configured(self) -> bool:
        return self.webhook_url.startswith("https://")


@dataclass(frozen=True, slots=True)
class EmailHandoffReceipt:
    status_code: int
    accepted_at: datetime
    response_text: str = ""


def ensure_buyer_can_receive_email(buyer: BuyerProfile) -> None:
    if buyer.do_not_contact:
        raise EmailHandoffError("This buyer is marked Do Not Contact. Email handoff is blocked.")
    if not buyer.email_consent:
        raise EmailHandoffError("This buyer does not have saved email consent. Email handoff is blocked.")
    if not buyer.email.strip():
        raise EmailHandoffError("This buyer does not have a saved email address.")


def _idempotency_key(
    *,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    campaign: str,
    subject: str,
    message: str,
) -> str:
    raw = "|".join(
        (
            str(buyer.buyer_id),
            str(property_record.property_id),
            campaign.strip().lower(),
            subject.strip(),
            message.strip(),
        )
    ).encode("utf-8")
    return "cfh-email-" + hashlib.sha256(raw).hexdigest()[:32]


def build_email_handoff_payload(
    *,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    campaign: str,
    subject: str,
    message: str,
    tracked_link: str,
    requested_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_buyer_can_receive_email(buyer)
    clean_subject = subject.strip()
    clean_message = message.strip()
    clean_link = tracked_link.strip()
    if not clean_subject:
        raise EmailHandoffError("The prepared email subject is empty.")
    if not clean_message:
        raise EmailHandoffError("The prepared email message is empty.")
    if not clean_link:
        raise EmailHandoffError("The tracked Dwelyx link is missing.")

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    campaign_name = campaign.strip() or "owner_finance_homes"
    idempotency_key = _idempotency_key(
        buyer=buyer,
        property_record=property_record,
        campaign=campaign_name,
        subject=clean_subject,
        message=clean_message,
    )

    return {
        "schema_version": EMAIL_HANDOFF_SCHEMA_VERSION,
        "event": EMAIL_HANDOFF_EVENT,
        "requested_at": timestamp.astimezone(UTC).isoformat(),
        "requested_by": requested_by.strip() or "CFH Marketing App",
        "idempotency_key": idempotency_key,
        "channel": "email",
        "recipient": {
            "buyer_id": str(buyer.buyer_id),
            "first_name": buyer.first_name,
            "last_name": buyer.last_name,
            "email": buyer.email,
            "email_consent_verified": True,
            "do_not_contact": False,
        },
        "marketing": {
            "property_id": str(property_record.property_id),
            "property_address": property_record.display_address,
            "campaign": campaign_name,
            "source": "credit_friendly_homes",
            "subject": clean_subject,
            "message": clean_message,
            "tracked_dwelyx_link": clean_link,
        },
        "compliance": {
            "saved_email_consent_required": True,
            "do_not_contact_blocked": True,
            "unsubscribe_handling_required_downstream": True,
            "do_not_change_subject_or_message": True,
            "do_not_invent_property_terms": True,
        },
        "instructions": {
            "required_action": (
                "Send exactly one email through the approved Credit Friendly Homes sender to the supplied recipient. "
                "Honor the idempotency key, preserve the exact subject/message/link, and process unsubscribe requests "
                "back into the approved consent/suppression workflow."
            ),
            "external_provider_credentials_owned_downstream": True,
        },
    }


def dispatch_email_handoff(
    values: Mapping[str, Any],
    *,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    campaign: str,
    subject: str,
    message: str,
    tracked_link: str,
    requested_by: str,
) -> EmailHandoffReceipt:
    settings = EmailHandoffSettings.from_mapping(values)
    if not settings.configured:
        raise EmailHandoffError(
            "Email sender is not connected. Add the approved HTTPS email automation endpoint as "
            "EMAIL_SENDER_WEBHOOK_URL in Streamlit Secrets."
        )

    payload = build_email_handoff_payload(
        buyer=buyer,
        property_record=property_record,
        campaign=campaign,
        subject=subject,
        message=message,
        tracked_link=tracked_link,
        requested_by=requested_by,
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = Request(
        settings.webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Credit-Friendly-Homes-Marketing/1.0",
            "X-CFH-Event": EMAIL_HANDOFF_EVENT,
            "X-CFH-Idempotency-Key": str(payload["idempotency_key"]),
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=EMAIL_HANDOFF_TIMEOUT_SECONDS) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:EMAIL_HANDOFF_RESPONSE_LIMIT]
        raise EmailHandoffError(
            f"The configured email automation rejected the handoff (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise EmailHandoffError("The configured email automation could not be reached.") from exc

    if not 200 <= status_code < 300:
        raise EmailHandoffError(f"The configured email automation returned HTTP {status_code}.")

    return EmailHandoffReceipt(
        status_code=status_code,
        accepted_at=datetime.now(UTC),
        response_text=response_text[:EMAIL_HANDOFF_RESPONSE_LIMIT],
    )
