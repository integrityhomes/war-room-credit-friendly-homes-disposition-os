from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .buyer_intent import BuyerPropertyMatch

BUYER_REACTIVATION_BLOCK_REASON = (
    "Buyer reactivation is handled by the consent-checked Buyer Reactivation Autopilot, "
    "not by the property-launch webhook."
)


def _recipient_row(
    match: BuyerPropertyMatch,
    recipient: str,
    *,
    recipient_type: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "buyer_id": match.buyer_id,
        "buyer_name": match.buyer_name,
        "recipient": recipient,
        "recipient_type": recipient_type,
        "intent_score": match.score,
        "intent_tier": match.tier.value,
        "tracked_dwelyx_link": match.tracked_link,
    }
    # Zapier field mapping works best when the contact value has an explicit name.
    # Keep the generic `recipient` field for backward compatibility while also
    # exposing `email` / `phone` so downstream actions can find them directly.
    if recipient_type == "email":
        row["email"] = recipient
    elif recipient_type == "sms":
        row["phone"] = recipient
    return row


def _build_execution_rows(channels: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return Zapier-ready rows with exactly one buyer contact per email/SMS row.

    ``channels`` remains the canonical 15-channel campaign catalog. Zapier should loop
    over ``execution_rows`` instead. Non-buyer channels stay one row each; email and
    SMS are expanded to one row per consent-ready buyer so actions that accept a single
    email address or phone number never receive an array or comma-separated value.
    """
    execution_rows: list[dict[str, Any]] = []

    for source_row in channels:
        row = deepcopy(dict(source_row))
        channel_key = str(row.get("channel_key", ""))

        if channel_key not in {"email", "sms"}:
            execution_rows.append(row)
            continue

        recipients = row.get("recipients", [])
        if not isinstance(recipients, list) or not recipients:
            # Preserve the blocked row so downstream path/filter behavior remains visible.
            execution_rows.append(row)
            continue

        for recipient in recipients:
            if not isinstance(recipient, Mapping):
                continue
            execution_row = deepcopy(row)
            execution_row["recipients"] = [dict(recipient)]
            execution_row["buyer_id"] = str(recipient.get("buyer_id", ""))
            execution_row["buyer_name"] = str(recipient.get("buyer_name", ""))
            execution_row["recipient"] = str(recipient.get("recipient", ""))
            execution_row["recipient_type"] = str(recipient.get("recipient_type", ""))
            execution_row["recipient_email"] = str(recipient.get("email", ""))
            execution_row["recipient_phone"] = str(recipient.get("phone", ""))
            execution_row["recipient_tracked_dwelyx_link"] = str(
                recipient.get("tracked_dwelyx_link", "")
            )
            execution_rows.append(execution_row)

    return execution_rows


def enrich_launch_payload_with_buyer_audience(
    payload: dict[str, Any],
    matches: Sequence[BuyerPropertyMatch],
) -> dict[str, Any]:
    """Attach only consent-ready buyers to property-launch email/SMS rows.

    The normal property campaign is allowed to hand each consent-ready buyer to REI BlackBook.
    Reactivation remains isolated in the dedicated autopilot so the same buyer is not contacted
    twice from one property launch.

    ``channels`` stays the 15-channel source-of-truth catalog. ``execution_rows`` is the
    downstream automation list and expands email/SMS to one row per buyer. This prevents
    Zapier from trying to map a list of phone numbers into a single-phone-number action.
    """
    email_recipients = [
        _recipient_row(match, match.email, recipient_type="email")
        for match in matches
        if match.email_allowed and match.email
    ]
    sms_recipients = [
        _recipient_row(match, match.phone, recipient_type="sms")
        for match in matches
        if match.sms_allowed and match.phone
    ]

    email_addresses = [str(row["email"]) for row in email_recipients]
    sms_phone_numbers = [str(row["phone"]) for row in sms_recipients]

    payload["buyer_audience"] = {
        "source": "Credit Friendly Homes saved buyer profiles + buyer-intent matching",
        "consent_checked": True,
        "do_not_contact_checked": True,
        "cooldown_checked": True,
        "email_recipient_count": len(email_recipients),
        "sms_recipient_count": len(sms_recipients),
        # Explicit arrays are useful for audit/inspection; execution_rows below provides
        # single-value aliases for Zapier actions that accept only one contact at a time.
        "email_recipient_addresses": email_addresses,
        "sms_recipient_phone_numbers": sms_phone_numbers,
        "reactivation_delegated_to_autopilot": True,
    }

    channels = {
        str(row.get("channel_key", "")): row
        for row in payload.get("channels", [])
        if isinstance(row, Mapping)
    }

    email_row = channels.get("email")
    if email_row is not None:
        email_row["recipient_mode"] = "per_buyer"
        email_row["recipients"] = email_recipients
        email_row["recipient_addresses"] = email_addresses
        if not email_recipients:
            email_row["posting_blocked"] = True
            email_row["block_reason"] = "No consent-ready buyer email recipients matched this property."

    sms_row = channels.get("sms")
    if sms_row is not None:
        sms_row["recipient_mode"] = "per_buyer"
        sms_row["recipients"] = sms_recipients
        sms_row["recipient_phone_numbers"] = sms_phone_numbers
        if not sms_recipients:
            sms_row["posting_blocked"] = True
            sms_row["block_reason"] = "No consent-ready buyer phone recipients matched this property."

    reactivation_row = channels.get("reactivation")
    if reactivation_row is not None:
        reactivation_row["recipient_mode"] = "delegated"
        reactivation_row["recipients"] = []
        reactivation_row["posting_blocked"] = True
        reactivation_row["block_reason"] = BUYER_REACTIVATION_BLOCK_REASON

    payload["execution_rows"] = _build_execution_rows(
        [row for row in payload.get("channels", []) if isinstance(row, Mapping)]
    )
    payload["execution_row_count"] = len(payload["execution_rows"])

    return payload
