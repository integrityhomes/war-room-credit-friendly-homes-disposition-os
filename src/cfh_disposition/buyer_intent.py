from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .dwelyx import build_dwelyx_url
from .models import BuyerProfile, OwnerFinanceProperty
from .storage import SupabaseSettings

BUYER_INTENT_BUCKET = "cfh-buyer-intent"
BUYER_INTENT_PATH = "buyer-intent/ledger.json"
BUYER_INTENT_MAX_BYTES = 2 * 1024 * 1024
REACTIVATION_COOLDOWN_DAYS = 14


class BuyerIntentError(RuntimeError):
    """Raised when buyer-intent scoring or outreach records cannot be completed."""


class IntentTier(StrEnum):
    HOT = "Hot"
    WARM = "Warm"
    NURTURE = "Nurture"
    NOT_ELIGIBLE = "Not Eligible"


class OutreachChannel(StrEnum):
    EMAIL = "Email"
    SMS = "SMS"


class BuyerEngagementSignal(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    buyer_id: str
    signal_type: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    property_id: str = ""
    value: int = Field(default=1, ge=0, le=100)
    notes: str = Field(default="", max_length=500)


class BuyerOutreachRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    outreach_id: str = Field(default_factory=lambda: str(uuid4()))
    buyer_id: str
    property_id: str
    channel: OutreachChannel
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    campaign: str = "buyer_reactivation"
    sent_by: str = ""
    outcome: str = "Prepared"
    notes: str = Field(default="", max_length=500)


class BuyerIntentLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    signals: list[BuyerEngagementSignal] = Field(default_factory=list)
    outreach: list[BuyerOutreachRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BuyerPropertyMatch:
    buyer_id: str
    buyer_name: str
    property_id: str
    property_address: str
    score: int
    tier: IntentTier
    reasons: tuple[str, ...]
    email_allowed: bool
    sms_allowed: bool
    email: str
    phone: str
    tracked_link: str
    email_subject: str
    email_body: str
    sms_message: str
    blocked_reason: str = ""


def _buyer_name(buyer: BuyerProfile) -> str:
    return " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip()


def _normalized(values: Sequence[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value.strip()}


def _recent_signals(
    ledger: BuyerIntentLedger,
    buyer_id: UUID | str,
    *,
    now: datetime,
    days: int = 90,
) -> list[BuyerEngagementSignal]:
    cutoff = now - timedelta(days=days)
    return [
        signal
        for signal in ledger.signals
        if signal.buyer_id == str(buyer_id) and signal.occurred_at >= cutoff
    ]


def _latest_outreach(
    ledger: BuyerIntentLedger,
    buyer_id: UUID | str,
    property_id: UUID | str,
    channel: OutreachChannel,
) -> BuyerOutreachRecord | None:
    matches = [
        row
        for row in ledger.outreach
        if row.buyer_id == str(buyer_id)
        and row.property_id == str(property_id)
        and row.channel == channel
    ]
    return max(matches, key=lambda row: row.sent_at) if matches else None


def outreach_ready(
    ledger: BuyerIntentLedger,
    buyer_id: UUID | str,
    property_id: UUID | str,
    channel: OutreachChannel,
    *,
    now: datetime | None = None,
    cooldown_days: int = REACTIVATION_COOLDOWN_DAYS,
) -> bool:
    current = now or datetime.now(UTC)
    latest = _latest_outreach(ledger, buyer_id, property_id, channel)
    return latest is None or current >= latest.sent_at + timedelta(days=cooldown_days)


def score_buyer_for_property(
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    ledger: BuyerIntentLedger,
    *,
    now: datetime | None = None,
) -> tuple[int, IntentTier, tuple[str, ...], str]:
    current = now or datetime.now(UTC)
    if buyer.do_not_contact:
        return 0, IntentTier.NOT_ELIGIBLE, (), "Buyer is marked Do Not Contact."
    if not buyer.email_consent and not buyer.sms_consent:
        return 0, IntentTier.NOT_ELIGIBLE, (), "No email or SMS consent is saved."

    score = 0
    reasons: list[str] = []
    cities = _normalized(buyer.preferred_cities)
    states = _normalized(buyer.preferred_states)
    city_match = not cities or property_record.city.casefold() in cities
    state_match = not states or property_record.state.casefold() in states
    if city_match and state_match:
        score += 30
        reasons.append("location match")
    elif state_match:
        score += 15
        reasons.append("state match")
    else:
        score -= 20
        reasons.append("outside preferred location")

    if buyer.minimum_bedrooms is None or (
        property_record.bedrooms is not None
        and property_record.bedrooms >= buyer.minimum_bedrooms
    ):
        score += 10
        reasons.append("bedroom match")
    else:
        score -= 15
        reasons.append("below bedroom minimum")

    if buyer.maximum_monthly_payment is not None and property_record.monthly_payment is not None:
        if property_record.monthly_payment <= buyer.maximum_monthly_payment:
            score += 20
            reasons.append("monthly payment fits")
        else:
            score -= 25
            reasons.append("monthly payment above stated maximum")

    if buyer.available_down_payment is not None and property_record.down_payment is not None:
        if buyer.available_down_payment >= property_record.down_payment:
            score += 20
            reasons.append("down payment fits")
        else:
            score -= 25
            reasons.append("down payment above stated funds")

    if buyer.move_timeframe_days is not None:
        if buyer.move_timeframe_days <= 30:
            score += 15
            reasons.append("moving within 30 days")
        elif buyer.move_timeframe_days <= 90:
            score += 8
            reasons.append("moving within 90 days")

    repair_text = (property_record.repairs_needed or "").casefold()
    tolerance = buyer.repair_tolerance.casefold()
    if repair_text and tolerance in {"none", "low"}:
        score -= 10
        reasons.append("repair tolerance may not fit")
    elif tolerance in {"medium", "high", "any"}:
        score += 5
        reasons.append("repair tolerance fits")

    signal_weights = {
        "dwelyx_click": 8,
        "property_view": 7,
        "reply": 12,
        "application_started": 20,
        "showing_requested": 25,
        "call_connected": 10,
        "email_open": 2,
        "sms_click": 8,
    }
    for signal in _recent_signals(ledger, buyer.buyer_id, now=current):
        weight = signal_weights.get(signal.signal_type.casefold(), 0)
        if signal.property_id == str(property_record.property_id):
            weight += 5
        score += min(weight * max(signal.value, 1), 30)
    if _recent_signals(ledger, buyer.buyer_id, now=current):
        reasons.append("recent engagement")

    score = max(0, min(score, 100))
    tier = (
        IntentTier.HOT
        if score >= 75
        else IntentTier.WARM
        if score >= 50
        else IntentTier.NURTURE
    )
    return score, tier, tuple(reasons), ""


def build_match(
    buyer: BuyerProfile,
    property_record: OwnerFinanceProperty,
    ledger: BuyerIntentLedger,
    dwelyx_url: str,
    *,
    now: datetime | None = None,
    campaign: str = "buyer_reactivation",
) -> BuyerPropertyMatch:
    current = now or datetime.now(UTC)
    score, tier, reasons, blocked_reason = score_buyer_for_property(
        buyer, property_record, ledger, now=current
    )
    tracked_link = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium="buyer_reactivation",
        campaign=campaign,
        property_id=property_record.property_id,
    )
    name = buyer.first_name or "there"
    payment = (
        f"${property_record.monthly_payment:,.0f} per month"
        if property_record.monthly_payment is not None
        else "monthly terms available in Dwelyx"
    )
    down = (
        f"${property_record.down_payment:,.0f} down"
        if property_record.down_payment is not None
        else "down-payment details available in Dwelyx"
    )
    address = property_record.display_address
    consent_line = "You are receiving this because you previously requested owner-finance home updates."
    email_subject = f"Owner-finance home match: {address}"
    email_body = (
        f"Hi {name},\n\nA home may match the preferences you previously shared: {address}.\n"
        f"Owner-finance terms currently shown: {down} and {payment}. The monthly payment is not rent.\n\n"
        f"Review the property and current availability through your Dwelyx buyer account:\n{tracked_link}\n\n"
        "Approval, terms, property condition, and availability are subject to review and verification. "
        "Equal Housing Opportunity.\n\n"
        f"{consent_line} Reply STOP or use the sender's unsubscribe process to stop messages."
    )
    sms_message = (
        f"Hi {name}, owner-finance match: {address}. {down}; {payment}. "
        f"Review current details in Dwelyx: {tracked_link} Reply STOP to opt out."
    )
    email_allowed = (
        buyer.email_consent
        and bool(buyer.email)
        and not buyer.do_not_contact
        and outreach_ready(
            ledger, buyer.buyer_id, property_record.property_id, OutreachChannel.EMAIL, now=current
        )
    )
    sms_allowed = (
        buyer.sms_consent
        and bool(buyer.phone)
        and not buyer.do_not_contact
        and outreach_ready(
            ledger, buyer.buyer_id, property_record.property_id, OutreachChannel.SMS, now=current
        )
    )
    return BuyerPropertyMatch(
        buyer_id=str(buyer.buyer_id),
        buyer_name=_buyer_name(buyer),
        property_id=str(property_record.property_id),
        property_address=address,
        score=score,
        tier=tier,
        reasons=reasons,
        email_allowed=email_allowed,
        sms_allowed=sms_allowed,
        email=buyer.email,
        phone=buyer.phone,
        tracked_link=tracked_link,
        email_subject=email_subject,
        email_body=email_body,
        sms_message=sms_message,
        blocked_reason=blocked_reason,
    )


def build_match_queue(
    buyers: Sequence[BuyerProfile],
    properties: Sequence[OwnerFinanceProperty],
    ledger: BuyerIntentLedger,
    dwelyx_url: str,
    *,
    now: datetime | None = None,
    minimum_score: int = 35,
) -> list[BuyerPropertyMatch]:
    matches = [
        build_match(buyer, property_record, ledger, dwelyx_url, now=now)
        for buyer in buyers
        for property_record in properties
    ]
    return sorted(
        [
            match
            for match in matches
            if match.score >= minimum_score
            and match.tier != IntentTier.NOT_ELIGIBLE
            and (match.email_allowed or match.sms_allowed)
        ],
        key=lambda match: (-match.score, match.buyer_name.casefold(), match.property_address.casefold()),
    )


def record_signal(
    ledger: BuyerIntentLedger,
    *,
    buyer_id: UUID | str,
    signal_type: str,
    property_id: UUID | str = "",
    value: int = 1,
    notes: str = "",
    occurred_at: datetime | None = None,
) -> BuyerIntentLedger:
    signal = BuyerEngagementSignal(
        buyer_id=str(buyer_id),
        signal_type=signal_type,
        property_id=str(property_id) if property_id else "",
        value=value,
        notes=notes,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    return ledger.model_copy(
        update={
            "signals": [*ledger.signals, signal],
            "updated_at": datetime.now(UTC),
        }
    )


def record_outreach(
    ledger: BuyerIntentLedger,
    match: BuyerPropertyMatch,
    *,
    channel: OutreachChannel,
    sent_by: str,
    outcome: str = "Prepared",
    notes: str = "",
    sent_at: datetime | None = None,
) -> BuyerIntentLedger:
    if channel == OutreachChannel.EMAIL and not match.email_allowed:
        raise BuyerIntentError("Email outreach is not allowed or is still inside its cooldown.")
    if channel == OutreachChannel.SMS and not match.sms_allowed:
        raise BuyerIntentError("SMS outreach is not allowed or is still inside its cooldown.")
    row = BuyerOutreachRecord(
        buyer_id=match.buyer_id,
        property_id=match.property_id,
        channel=channel,
        sent_by=sent_by,
        outcome=outcome,
        notes=notes,
        sent_at=sent_at or datetime.now(UTC),
    )
    return ledger.model_copy(
        update={
            "outreach": [*ledger.outreach, row],
            "updated_at": datetime.now(UTC),
        }
    )


def match_rows(matches: Sequence[BuyerPropertyMatch]) -> list[dict[str, str | int]]:
    return [
        {
            "Intent": match.tier.value,
            "Score": match.score,
            "Buyer": match.buyer_name,
            "Property": match.property_address,
            "Email Ready": "Yes" if match.email_allowed else "No",
            "SMS Ready": "Yes" if match.sms_allowed else "No",
            "Why": ", ".join(match.reasons) or "—",
        }
        for match in matches
    ]


class BuyerIntentStore:
    """Private Supabase Storage ledger for engagement and reactivation history."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise BuyerIntentError("Supabase is not configured for buyer-intent records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise BuyerIntentError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(BUYER_INTENT_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    BUYER_INTENT_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": BUYER_INTENT_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise BuyerIntentError("Could not create the private buyer-intent bucket.") from exc
        self._bucket_ready = True

    def load(self) -> BuyerIntentLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(BUYER_INTENT_BUCKET).download(BUYER_INTENT_PATH)
        except Exception:
            return BuyerIntentLedger()
        try:
            payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
            return BuyerIntentLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise BuyerIntentError("The saved buyer-intent ledger could not be read.") from exc

    def save(self, ledger: BuyerIntentLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode()
        if len(payload) > BUYER_INTENT_MAX_BYTES:
            raise BuyerIntentError("The buyer-intent ledger is too large to save.")
        try:
            self._client.storage.from_(BUYER_INTENT_BUCKET).upload(
                path=BUYER_INTENT_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise BuyerIntentError("Could not save buyer-intent records.") from exc
