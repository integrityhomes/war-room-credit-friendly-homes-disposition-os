from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import BuyerProfile, OwnerFinanceProperty

SMS_HANDOFF_TIMEOUT_SECONDS = 15
SMS_HANDOFF_RESPONSE_LIMIT = 2000
SMS_HANDOFF_EVENT = "credit_friendly_homes.marketing.sms_handoff"
SMS_HANDOFF_SCHEMA_VERSION = "1.0"


class ReiBlackBookSmsError(RuntimeError):
    """Raised when CFH cannot safely hand a marketing SMS to REI BlackBook / Profit Dial."""


@dataclass(frozen=True, slots=True)
class SmsHandoffSettings:
    webhook_url: str = ""

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "SmsHandoffSettings":
        # SMS_SENDER_WEBHOOK_URL is intentionally the only required connection detail.
        # For the documented Zapier -> REI BlackBook path, Zapier owns the REI BlackBook
        # connection/authentication. CFH must not store or invent Profit Dial credentials.
        return cls(webhook_url=str(values.get("SMS_SENDER_WEBHOOK_URL", "")).strip())

    @property
    def configured(self) -> bool:
        return self.webhook_url.startswith("https://")


@dataclass(frozen=True, slots=True)
class SmsHandoffReceipt:
    status_code: int
    accepted_at: datetime
    response_text: str = ""


def ensure_buyer_can_receive_sms(buyer: BuyerProfile) -> None:
    if buyer.do_not_contact:
        raise ReiBlackBookSmsError("This buyer is marked Do Not Contact. SMS handoff is blocked.")
    if not buyer.sms_consent:
        raise ReiBlackBookSmsError("This buyer does not have saved SMS consent. SMS handoff is blocked.")
    if not buyer.phone.strip():
        raise ReiBlackBookSmsError("This buyer does not have a saved phone number.")


def build_sms_handoff_payload(
    *,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    campaign: str,
    message: str,
    tracked_link: str,
    requested_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_buyer_can_receive_sms(buyer)
    clean_message = message.strip()
    if not clean_message:
        raise ReiBlackBookSmsError("The prepared SMS message is empty.")
    if not tracked_link.strip():
        raise ReiBlackBookSmsError("The tracked Dwelyx link is missing.")

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    return {
        "schema_version": SMS_HANDOFF_SCHEMA_VERSION,
        "event": SMS_HANDOFF_EVENT,
        "requested_at": timestamp.astimezone(UTC).isoformat(),
        "requested_by": requested_by.strip() or "CFH Marketing App",
        "sender_system": "rei_blackbook_profit_dial",
        "action": "create_or_update_contact_and_run_sms_workflow",
        "buyer": {
            "buyer_id": str(buyer.buyer_id),
            "first_name": buyer.first_name,
            "last_name": buyer.last_name,
            "phone": buyer.phone,
        },
        "marketing": {
            "property_id": str(property_record.property_id),
            "property_address": property_record.display_address,
            "campaign": campaign.strip() or "owner_finance_homes",
            "source": "credit_friendly_homes",
            "channel": "sms",
            "message": clean_message,
            "tracked_dwelyx_link": tracked_link.strip(),
        },
        "instructions": {
            "destination": "REI BlackBook / Profit Dial",
            "required_action": "Create or update the contact by phone, then run the approved CFH owner-finance SMS workflow using the configured Profit Dial number.",
            "do_not_change_message": True,
        },
    }


def dispatch_sms_handoff(
    values: Mapping[str, Any],
    *,
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    campaign: str,
    message: str,
    tracked_link: str,
    requested_by: str,
) -> SmsHandoffReceipt:
    settings = SmsHandoffSettings.from_mapping(values)
    if not settings.configured:
        raise ReiBlackBookSmsError(
            "SMS sender is not connected. Add the real Zapier Catch Hook URL as SMS_SENDER_WEBHOOK_URL in Streamlit Secrets."
        )

    payload = build_sms_handoff_payload(
        buyer=buyer,
        property_record=property_record,
        campaign=campaign,
        message=message,
        tracked_link=tracked_link,
        requested_by=requested_by,
    )
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        settings.webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Credit-Friendly-Homes-Marketing/1.0",
            "X-CFH-Event": SMS_HANDOFF_EVENT,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=SMS_HANDOFF_TIMEOUT_SECONDS) as response:
            status_code = int(getattr(response, "status", 200))
            response_text = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:SMS_HANDOFF_RESPONSE_LIMIT]
        raise ReiBlackBookSmsError(
            f"REI BlackBook / Profit Dial handoff was rejected (HTTP {exc.code}). {detail}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ReiBlackBookSmsError(
            "REI BlackBook / Profit Dial handoff could not reach the configured Zapier webhook."
        ) from exc

    if not 200 <= status_code < 300:
        raise ReiBlackBookSmsError(
            f"REI BlackBook / Profit Dial handoff returned HTTP {status_code}."
        )

    return SmsHandoffReceipt(
        status_code=status_code,
        accepted_at=datetime.now(UTC),
        response_text=response_text[:SMS_HANDOFF_RESPONSE_LIMIT],
    )
