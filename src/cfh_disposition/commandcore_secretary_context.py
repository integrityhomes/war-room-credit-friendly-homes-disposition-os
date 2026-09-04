"""Read-only CommandCore CRM context adapter for Secretary test mode."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .commandcore_secretary_orchestrator import (
    CanonicalCommunicationEvent,
    CommunicationChannel,
    CommunicationDirection,
    SecretaryContactContext,
    SecretaryDealContext,
    SecretaryOrchestratorResult,
    SecretaryPropertyContext,
    SecretaryRoutingConfiguration,
    decide_secretary_action,
)


class MatchQuality(StrEnum):
    EXACT = "Exact"
    EXACT_RELATIONSHIP = "Exact existing relationship"
    ONE_ACTIVE_DEAL = "One unambiguous active deal"
    NOT_LINKED = "Not linked"
    AMBIGUOUS = "Ambiguous — needs human review"
    MISSING = "Missing evidence — needs human review"


class ConsentReadState(StrEnum):
    DO_NOT_CONTACT = "Do not contact"
    SUPPRESSED = "Suppressed"
    CONSENT_RECORDED = "Consent recorded"
    NO_CONSENT_RECORDED = "No consent recorded"
    UNKNOWN = "Unknown"


class SecretaryMatchQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    contact: MatchQuality
    property: MatchQuality
    deal: MatchQuality
    routing_source: str


class SecretaryLiveContextResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: SecretaryOrchestratorResult
    person_label: str
    relationship: str
    property_label: str
    deal_label: str
    current_deal_owner: str
    consent_state: ConsentReadState
    match_quality: SecretaryMatchQuality
    records_written: int = 0
    tasks_created: int = 0
    consent_mutations: int = 0
    external_actions_started: int = 0


def _text(value: object) -> str:
    return str(value or "").strip()


def _links(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("links")
    return value if isinstance(value, Mapping) else {}


def _id(record: Mapping[str, Any]) -> str:
    return _text(record.get("id") or record.get("external_id"))


def _phone(value: object) -> str:
    digits = re.sub(r"\D", "", _text(value))
    return digits[-10:] if len(digits) >= 10 else digits


def _active(deal: Mapping[str, Any]) -> bool:
    status = _text(deal.get("status")).casefold()
    stage = _text(deal.get("stage")).casefold()
    return status not in {"closed", "dead", "cancelled", "canceled"} and stage not in {
        "closed",
        "dead / not moving forward",
    }


def _channel(value: object) -> CommunicationChannel:
    text = _text(value).casefold()
    aliases = {
        "sms": CommunicationChannel.SMS,
        "text": CommunicationChannel.SMS,
        "phone": CommunicationChannel.PHONE,
        "call": CommunicationChannel.PHONE,
        "email": CommunicationChannel.EMAIL,
        "website": CommunicationChannel.WEBSITE,
        "facebook": CommunicationChannel.FACEBOOK,
        "messenger": CommunicationChannel.FACEBOOK,
    }
    return aliases.get(text, CommunicationChannel.OTHER)


def _direction(value: object) -> CommunicationDirection:
    return CommunicationDirection.OUTBOUND if _text(value).casefold() == "outbound" else CommunicationDirection.INBOUND


def _message(record: Mapping[str, Any]) -> str:
    for field in ("message_text", "body", "message", "content", "summary"):
        if value := _text(record.get(field)):
            return value
    return "Message content unavailable"


def safe_communication_label(record: Mapping[str, Any], contacts: Sequence[Mapping[str, Any]]) -> str:
    """Build a selection label without phone, email, or message content."""
    contact_id = _text(_links(record).get("contact_id") or record.get("contact_id"))
    contact = next((item for item in contacts if _id(item) == contact_id), None)
    person = _text((contact or {}).get("name")) or contact_id or "Unmatched contact"
    created = _text(record.get("created_at") or record.get("occurred_at")) or "Date unavailable"
    channel = _channel(record.get("channel")).value
    direction = _direction(record.get("direction")).value
    deal_id = _text(_links(record).get("deal_id") or record.get("deal_id"))
    suffix = f" · Deal {deal_id}" if deal_id else ""
    return f"{created} · {channel} · {direction} · {person}{suffix}"


def _contact_match(
    communication: Mapping[str, Any], contacts: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, MatchQuality]:
    linked_id = _text(_links(communication).get("contact_id") or communication.get("contact_id"))
    if linked_id:
        matches = [item for item in contacts if _id(item) == linked_id]
    else:
        phone = _phone(communication.get("contact_phone") or communication.get("phone"))
        email = _text(communication.get("contact_email") or communication.get("email")).casefold()
        matches = [
            item
            for item in contacts
            if (phone and _phone(item.get("phone")) == phone)
            or (email and _text(item.get("email")).casefold() == email)
        ]
    unique = {_id(item): item for item in matches if _id(item)}
    if len(unique) == 1:
        return next(iter(unique.values())), MatchQuality.EXACT
    return None, MatchQuality.AMBIGUOUS if len(unique) > 1 else MatchQuality.MISSING if linked_id else MatchQuality.NOT_LINKED


def _property_match(
    communication: Mapping[str, Any], properties: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, MatchQuality]:
    linked_id = _text(_links(communication).get("property_id") or communication.get("property_id"))
    if linked_id:
        matches = [item for item in properties if _id(item) == linked_id]
    else:
        address = _text(communication.get("property_address")).casefold()
        matches = [item for item in properties if address and _text(item.get("address")).casefold() == address]
    unique = {_id(item): item for item in matches if _id(item)}
    if len(unique) == 1:
        return next(iter(unique.values())), MatchQuality.EXACT
    return None, MatchQuality.AMBIGUOUS if len(unique) > 1 else MatchQuality.MISSING if linked_id else MatchQuality.NOT_LINKED


def _deal_match(
    communication: Mapping[str, Any],
    deals: Sequence[Mapping[str, Any]],
    contact: Mapping[str, Any] | None,
    property_: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, MatchQuality]:
    explicit_id = _text(_links(communication).get("deal_id") or communication.get("deal_id"))
    if explicit_id:
        matches = [item for item in deals if _id(item) == explicit_id]
        return (matches[0], MatchQuality.EXACT) if len(matches) == 1 else (None, MatchQuality.MISSING if not matches else MatchQuality.AMBIGUOUS)

    contact_id = _id(contact or {})
    property_id = _id(property_ or {})
    contact_deals = [item for item in deals if contact_id and _text(_links(item).get("contact_id") or item.get("contact_id")) == contact_id]
    property_deals = [item for item in deals if property_id and _text(_links(item).get("property_id") or item.get("property_id")) == property_id]
    candidates = contact_deals
    quality = MatchQuality.EXACT_RELATIONSHIP
    if contact_deals and property_deals:
        property_ids = {_id(item) for item in property_deals}
        candidates = [item for item in contact_deals if _id(item) in property_ids]
    elif property_deals:
        candidates = property_deals
    unique = {_id(item): item for item in candidates if _id(item)}
    if len(unique) == 1:
        return next(iter(unique.values())), quality
    if len(unique) > 1 and contact_id:
        active = {key: item for key, item in unique.items() if _active(item)}
        if len(active) == 1:
            return next(iter(active.values())), MatchQuality.ONE_ACTIVE_DEAL
    return None, MatchQuality.AMBIGUOUS if len(unique) > 1 else MatchQuality.NOT_LINKED


def _consent(
    contact: Mapping[str, Any] | None,
    consent_record: Mapping[str, Any] | None,
) -> ConsentReadState:
    if not contact:
        return ConsentReadState.UNKNOWN
    if consent_record:
        if consent_record.get("suppressed") is True:
            return ConsentReadState.SUPPRESSED
        states = {
            _text(consent_record.get("sms_consent_state")).casefold(),
            _text(consent_record.get("email_consent_state")).casefold(),
        }
        if "opt_out" in states or "revoked" in states:
            return ConsentReadState.DO_NOT_CONTACT
        if "granted" in states:
            return ConsentReadState.CONSENT_RECORDED
        return ConsentReadState.NO_CONSENT_RECORDED
    if contact.get("do_not_contact") is True:
        return ConsentReadState.DO_NOT_CONTACT
    if contact.get("suppressed") is True or _text(contact.get("consent_status")).casefold() in {"revoked", "suppressed", "opted out"}:
        return ConsentReadState.SUPPRESSED
    if any(contact.get(field) is True for field in ("sms_consent", "email_consent", "call_consent")):
        return ConsentReadState.CONSENT_RECORDED
    return ConsentReadState.NO_CONSENT_RECORDED


def evaluate_commandcore_communication(
    communication: Mapping[str, Any],
    *,
    contacts: Sequence[Mapping[str, Any]],
    properties: Sequence[Mapping[str, Any]],
    deals: Sequence[Mapping[str, Any]],
    routing: SecretaryRoutingConfiguration | None = None,
    consent_record: Mapping[str, Any] | None = None,
) -> SecretaryLiveContextResult:
    """Evaluate existing CRM data without mutating it or starting external work."""
    contact, contact_quality = _contact_match(communication, contacts)
    property_, property_quality = _property_match(communication, properties)
    deal, deal_quality = _deal_match(communication, deals, contact, property_)
    if deal and not contact:
        linked_contact = _text(_links(deal).get("contact_id") or deal.get("contact_id"))
        matches = [item for item in contacts if _id(item) == linked_contact]
        if len(matches) == 1:
            contact, contact_quality = matches[0], MatchQuality.EXACT_RELATIONSHIP
        elif len(matches) > 1:
            contact_quality = MatchQuality.AMBIGUOUS
    if deal and not property_:
        linked_property = _text(_links(deal).get("property_id") or deal.get("property_id"))
        matches = [item for item in properties if _id(item) == linked_property]
        if len(matches) == 1:
            property_, property_quality = matches[0], MatchQuality.EXACT_RELATIONSHIP
        elif len(matches) > 1:
            property_quality = MatchQuality.AMBIGUOUS

    event_id = _id(communication)
    if not event_id:
        raise ValueError("An existing communication event reference is required")
    event = CanonicalCommunicationEvent(
        communication_event_id=event_id,
        channel=_channel(communication.get("channel")),
        direction=_direction(communication.get("direction")),
        message_text=_message(communication),
        contact_id=_id(contact or {}),
        property_id=_id(property_ or {}),
        deal_id=_id(deal or {}),
        inbox=_text(communication.get("inbox")),
    )
    deal_owner = _text((deal or {}).get("assigned_to") or (deal or {}).get("assigned_worker"))
    contact_owner = _text((contact or {}).get("assigned_to") or (contact or {}).get("assigned_worker"))
    configured = routing or SecretaryRoutingConfiguration()
    routing_source = (
        "Existing deal owner"
        if deal_owner
        else "Existing contact owner"
        if contact_owner
        else "Configured inbox owner"
        if configured.inbox_owners.get(event.inbox)
        else "Configured channel owner"
        if configured.channel_owners.get(event.channel.value)
        else "Management review"
    )
    uncertain = any(
        quality in {MatchQuality.AMBIGUOUS, MatchQuality.MISSING}
        for quality in (contact_quality, property_quality, deal_quality)
    ) or not (deal_owner or contact_owner or configured.inbox_owners.get(event.inbox) or configured.channel_owners.get(event.channel.value))
    decision = decide_secretary_action(
        event,
        contacts=(
            SecretaryContactContext(
                contact_id=_id(contact),
                phone=_text(contact.get("phone")),
                email=_text(contact.get("email")),
                relationship=_text(contact.get("relationship") or contact.get("contact_type") or contact.get("lead_type")),
                assigned_worker=contact_owner,
            ),
        ) if contact else (),
        properties=(SecretaryPropertyContext(property_id=_id(property_), safe_label=_text(property_.get("address"))),) if property_ else (),
        deals=(
            (
                SecretaryDealContext(
                    deal_id=_id(deal),
                    contact_id=_text(
                        _links(deal).get("contact_id") or deal.get("contact_id")
                    ),
                    property_id=_text(
                        _links(deal).get("property_id") or deal.get("property_id")
                    ),
                    assigned_worker=deal_owner,
                ),
            )
            if deal
            else ()
        ),
        routing=configured,
        context_uncertain=uncertain,
        uncertainty_evidence="CommandCore context is ambiguous or has no reliable assigned worker.",
    )
    person = _text((contact or {}).get("name")) or _id(contact or {}) or "Not reliably matched"
    relationship = _text((contact or {}).get("relationship") or (contact or {}).get("contact_type") or (contact or {}).get("lead_type")) or "Unknown"
    property_label = _text((property_ or {}).get("address")) or _id(property_ or {}) or "Not reliably matched"
    deal_label = _text((deal or {}).get("title")) or _id(deal or {}) or "Not reliably matched"
    return SecretaryLiveContextResult(
        decision=decision,
        person_label=person,
        relationship=relationship,
        property_label=property_label,
        deal_label=deal_label,
        current_deal_owner=deal_owner or "Unassigned",
        consent_state=_consent(contact, consent_record),
        match_quality=SecretaryMatchQuality(
            contact=contact_quality,
            property=property_quality,
            deal=deal_quality,
            routing_source=routing_source,
        ),
    )
