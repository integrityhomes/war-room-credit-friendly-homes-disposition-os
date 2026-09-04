"""Deterministic, provider-neutral Secretary orchestration in test mode only."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommunicationChannel(StrEnum):
    SMS = "SMS"
    PHONE = "Phone"
    EMAIL = "Email"
    WEBSITE = "Website"
    FACEBOOK = "Facebook"
    OTHER = "Other"


class CommunicationDirection(StrEnum):
    INBOUND = "Inbound"
    OUTBOUND = "Outbound"


class SecretaryIntent(StrEnum):
    SELLER_LEAD = "Seller lead"
    BUYER_LEAD = "Buyer lead"
    EXISTING_SELLER_FOLLOW_UP = "Existing seller follow-up"
    EXISTING_BUYER_FOLLOW_UP = "Existing buyer follow-up"
    DEAL_QUESTION = "Deal question"
    OFFER_PRICE_DISCUSSION = "Offer or price discussion"
    APPOINTMENT_REQUEST = "Appointment or scheduling request"
    DOCUMENT_CONTRACT_QUESTION = "Document or contract question"
    TITLE_CLOSING = "Title or closing communication"
    MARKETING_DISPOSITION_RESPONSE = "Marketing or disposition response"
    PAYMENT_MONEY = "Payment or money-related communication"
    LEGAL_COMPLIANCE = "Legal or compliance-sensitive communication"
    COMPLAINT_ESCALATION = "Complaint or escalation"
    CONSENT_STOP = "Unsubscribe, stop, or consent request"
    WRONG_NUMBER = "Wrong number or unrelated"
    UNKNOWN = "Unknown — needs human review"


class SecretaryUrgency(StrEnum):
    ROUTINE = "Routine"
    PROMPT = "Prompt"
    HIGH = "High"
    IMMEDIATE = "Immediate"


class SecretaryConfidence(StrEnum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INSUFFICIENT = "Insufficient — needs human review"


class CanonicalCommunicationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    communication_event_id: str = Field(min_length=1, max_length=200)
    channel: CommunicationChannel
    direction: CommunicationDirection
    message_text: str = Field(min_length=1, max_length=10000)
    contact_id: str = ""
    property_id: str = ""
    deal_id: str = ""
    contact_phone: str = ""
    contact_email: str = ""
    inbox: str = ""
    external_action_started: bool = False

    @model_validator(mode="after")
    def block_external_execution(self) -> CanonicalCommunicationEvent:
        if self.external_action_started:
            raise ValueError("Secretary test events cannot start external actions")
        return self


class SecretaryContactContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_id: str
    phone: str = ""
    email: str = ""
    relationship: str = ""
    assigned_worker: str = ""


class SecretaryPropertyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    property_id: str
    safe_label: str = ""


class SecretaryDealContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    deal_id: str
    contact_id: str = ""
    property_id: str = ""
    assigned_worker: str = ""


class SecretaryRoutingConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    inbox_owners: Mapping[str, str] = Field(default_factory=dict)
    channel_owners: Mapping[str, str] = Field(default_factory=dict)


class SecretaryOrchestratorResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    communication_event_id: str
    channel: CommunicationChannel
    direction: CommunicationDirection
    matched_contact_id: str | None = None
    matched_property_id: str | None = None
    matched_deal_id: str | None = None
    intent: SecretaryIntent
    urgency: SecretaryUrgency
    confidence: SecretaryConfidence
    evidence: tuple[str, ...]
    suggested_owner: str
    suggested_action: str
    response_needed: bool
    task_needed: bool
    approval_required: bool
    approval_reason: str
    escalation_required: bool
    escalation_reason: str
    draft_response: str
    prohibited_external_action: bool = True
    model_provider: str = "Deterministic rules — no provider call"
    model_prompt_version: str = "commandcore-secretary-test-v1"
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def enforce_test_mode(self) -> SecretaryOrchestratorResult:
        if not self.prohibited_external_action:
            raise ValueError("Secretary test mode must prohibit external actions")
        if self.approval_required and not self.escalation_required:
            raise ValueError("Approval-required decisions must escalate for human review")
        return self


def _phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits[-10:] if len(digits) >= 10 else digits


def _one_or_ambiguous(items: Sequence[BaseModel]) -> tuple[BaseModel | None, bool]:
    unique = {
        str(
            getattr(
                item,
                "deal_id"
                if isinstance(item, SecretaryDealContext)
                else "property_id"
                if isinstance(item, SecretaryPropertyContext)
                else "contact_id",
            )
        ): item
        for item in items
    }
    return (next(iter(unique.values())), False) if len(unique) == 1 else (None, len(unique) > 1)


def _match_contact(event: CanonicalCommunicationEvent, contacts: Sequence[SecretaryContactContext]) -> tuple[SecretaryContactContext | None, bool]:
    if event.contact_id:
        return _one_or_ambiguous([item for item in contacts if item.contact_id == event.contact_id])  # type: ignore[return-value]
    phone = _phone(event.contact_phone)
    email = event.contact_email.casefold()
    candidates = [
        item
        for item in contacts
        if (phone and _phone(item.phone) == phone) or (email and item.email.casefold() == email)
    ]
    return _one_or_ambiguous(candidates)  # type: ignore[return-value]


def _match_property(event: CanonicalCommunicationEvent, properties: Sequence[SecretaryPropertyContext]) -> tuple[SecretaryPropertyContext | None, bool]:
    if not event.property_id:
        return None, False
    return _one_or_ambiguous([item for item in properties if item.property_id == event.property_id])  # type: ignore[return-value]


def _match_deal(
    event: CanonicalCommunicationEvent,
    deals: Sequence[SecretaryDealContext],
    contact: SecretaryContactContext | None,
    property_: SecretaryPropertyContext | None,
) -> tuple[SecretaryDealContext | None, bool]:
    if event.deal_id:
        return _one_or_ambiguous([item for item in deals if item.deal_id == event.deal_id])  # type: ignore[return-value]
    candidates = list(deals)
    if contact:
        candidates = [item for item in candidates if item.contact_id == contact.contact_id]
    if property_:
        candidates = [item for item in candidates if item.property_id == property_.property_id]
    if not contact and not property_:
        return None, False
    return _one_or_ambiguous(candidates)  # type: ignore[return-value]


def _contains(text: str, terms: Sequence[str]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)


def _classify(text: str, relationship: str, matched_deal: bool) -> tuple[SecretaryIntent, SecretaryUrgency, SecretaryConfidence, tuple[str, ...]]:
    if re.search(r"\b(stop|unsubscribe|opt[ -]?out|do not (?:text|call|contact|message))\b", text):
        return SecretaryIntent.CONSENT_STOP, SecretaryUrgency.IMMEDIATE, SecretaryConfidence.HIGH, ("Clear stop or opt-out language was detected.",)
    if _contains(text, ("wrong number", "not me", "unrelated")):
        return SecretaryIntent.WRONG_NUMBER, SecretaryUrgency.HIGH, SecretaryConfidence.HIGH, ("The sender indicated this contact is wrong or unrelated.",)
    if _contains(text, ("complaint", "angry", "threat", "fraud", "scam")):
        return SecretaryIntent.COMPLAINT_ESCALATION, SecretaryUrgency.IMMEDIATE, SecretaryConfidence.HIGH, ("Complaint, threat, fraud, or escalation language was detected.",)
    if _contains(text, ("bank", "routing", "wire", "payment", "money", "account number", "settlement")):
        return SecretaryIntent.PAYMENT_MONEY, SecretaryUrgency.IMMEDIATE, SecretaryConfidence.HIGH, ("Money, payment, settlement, or banking language was detected.",)
    if _contains(text, ("lawyer", "attorney", "lawsuit", "legal", "discrimination", "fair housing", "regulator")):
        return SecretaryIntent.LEGAL_COMPLIANCE, SecretaryUrgency.IMMEDIATE, SecretaryConfidence.HIGH, ("Legal or compliance-sensitive language was detected.",)
    if _contains(text, ("change contract", "amend contract", "change terms", "rewrite agreement", "cancel contract")):
        return SecretaryIntent.DOCUMENT_CONTRACT_QUESTION, SecretaryUrgency.HIGH, SecretaryConfidence.HIGH, ("A contract or binding-term change was requested.",)
    if _contains(text, ("title", "closing", "close date", "escrow")):
        return SecretaryIntent.TITLE_CLOSING, SecretaryUrgency.HIGH, SecretaryConfidence.HIGH, ("Title or closing language was detected.",)
    if _contains(text, ("offer", "price", "counteroffer", "discount", "down payment")):
        return SecretaryIntent.OFFER_PRICE_DISCUSSION, SecretaryUrgency.HIGH, SecretaryConfidence.HIGH, ("Offer, price, or financing-term language was detected.",)
    if _contains(text, ("appointment", "schedule", "showing", "tour", "meet", "available time")):
        return SecretaryIntent.APPOINTMENT_REQUEST, SecretaryUrgency.PROMPT, SecretaryConfidence.HIGH, ("Scheduling or appointment language was detected.",)
    if _contains(text, ("document", "contract", "agreement", "signature", "sign")):
        return SecretaryIntent.DOCUMENT_CONTRACT_QUESTION, SecretaryUrgency.HIGH, SecretaryConfidence.HIGH, ("Document, contract, or signature language was detected.",)
    if _contains(text, ("ad", "listing", "facebook", "marketplace", "marketing")):
        return SecretaryIntent.MARKETING_DISPOSITION_RESPONSE, SecretaryUrgency.PROMPT, SecretaryConfidence.MEDIUM, ("The message refers to a listing or marketing response.",)
    seller = relationship.casefold() == "seller" or _contains(text, ("sell", "selling", "my property", "my house"))
    buyer = relationship.casefold() in {"buyer", "investor"} or _contains(text, ("buy", "buying", "interested in home", "looking for home"))
    follow_up = _contains(text, ("follow up", "following up", "checking in", "any update"))
    if follow_up and seller:
        return SecretaryIntent.EXISTING_SELLER_FOLLOW_UP, SecretaryUrgency.PROMPT, SecretaryConfidence.HIGH, ("A known seller sent follow-up language.",)
    if follow_up and buyer:
        return SecretaryIntent.EXISTING_BUYER_FOLLOW_UP, SecretaryUrgency.PROMPT, SecretaryConfidence.HIGH, ("A known buyer sent follow-up language.",)
    if matched_deal and _contains(text, ("deal", "status", "update", "question", "what happens next")):
        return SecretaryIntent.DEAL_QUESTION, SecretaryUrgency.PROMPT, SecretaryConfidence.MEDIUM, ("A matched deal and general deal-question language were found.",)
    if seller:
        intent = SecretaryIntent.EXISTING_SELLER_FOLLOW_UP if matched_deal or follow_up else SecretaryIntent.SELLER_LEAD
        return intent, SecretaryUrgency.PROMPT, SecretaryConfidence.HIGH, ("Seller relationship or seller-intent language was detected.",)
    if buyer:
        intent = SecretaryIntent.EXISTING_BUYER_FOLLOW_UP if matched_deal or follow_up else SecretaryIntent.BUYER_LEAD
        return intent, SecretaryUrgency.PROMPT, SecretaryConfidence.HIGH, ("Buyer relationship or buyer-intent language was detected.",)
    return SecretaryIntent.UNKNOWN, SecretaryUrgency.PROMPT, SecretaryConfidence.LOW, ("The message did not match a safe deterministic intent.",)


_HIGH_RISK = {
    SecretaryIntent.PAYMENT_MONEY,
    SecretaryIntent.LEGAL_COMPLIANCE,
    SecretaryIntent.DOCUMENT_CONTRACT_QUESTION,
    SecretaryIntent.TITLE_CLOSING,
    SecretaryIntent.OFFER_PRICE_DISCUSSION,
    SecretaryIntent.COMPLAINT_ESCALATION,
    SecretaryIntent.CONSENT_STOP,
}


def decide_secretary_action(
    event: CanonicalCommunicationEvent,
    *,
    contacts: Sequence[SecretaryContactContext] = (),
    properties: Sequence[SecretaryPropertyContext] = (),
    deals: Sequence[SecretaryDealContext] = (),
    routing: SecretaryRoutingConfiguration | None = None,
    now: datetime | None = None,
) -> SecretaryOrchestratorResult:
    """Classify and recommend internal action without executing or persisting it."""
    contact, contact_ambiguous = _match_contact(event, contacts)
    property_, property_ambiguous = _match_property(event, properties)
    deal, deal_ambiguous = _match_deal(event, deals, contact, property_)
    if deal and not property_ and deal.property_id:
        property_matches = [item for item in properties if item.property_id == deal.property_id]
        property_, property_ambiguous = _one_or_ambiguous(property_matches)  # type: ignore[assignment]

    ambiguous = contact_ambiguous or property_ambiguous or deal_ambiguous
    relationship = contact.relationship if contact else ""
    intent, urgency, confidence, evidence = _classify(
        event.message_text.casefold(), relationship, deal is not None
    )
    if ambiguous:
        intent = SecretaryIntent.UNKNOWN
        urgency = SecretaryUrgency.HIGH
        confidence = SecretaryConfidence.INSUFFICIENT
        evidence = ("More than one CRM record could match this communication.",)

    configured = routing or SecretaryRoutingConfiguration()
    owner = (
        (deal.assigned_worker if deal else "")
        or (contact.assigned_worker if contact else "")
        or configured.inbox_owners.get(event.inbox, "")
        or configured.channel_owners.get(event.channel.value, "")
        or "Unassigned — management review required"
    )
    high_risk = intent in _HIGH_RISK
    unknown = intent is SecretaryIntent.UNKNOWN
    escalation = high_risk or unknown or ambiguous
    approval = high_risk
    response_needed = event.direction is CommunicationDirection.INBOUND and intent not in {
        SecretaryIntent.CONSENT_STOP,
        SecretaryIntent.WRONG_NUMBER,
    }
    action = (
        "Route to a human for controlled review before any response or record change."
        if escalation
        else "Review the suggested follow-up and prepare it in the existing CommandCore workflow."
    )
    draft = ""
    if response_needed and not escalation:
        draft = "Thank you for reaching out. A team member will review your request and follow up."
    return SecretaryOrchestratorResult(
        communication_event_id=event.communication_event_id,
        channel=event.channel,
        direction=event.direction,
        matched_contact_id=contact.contact_id if contact else None,
        matched_property_id=property_.property_id if property_ else None,
        matched_deal_id=deal.deal_id if deal else None,
        intent=intent,
        urgency=urgency,
        confidence=confidence,
        evidence=evidence,
        suggested_owner=owner,
        suggested_action=action,
        response_needed=response_needed,
        task_needed=event.direction is CommunicationDirection.INBOUND and intent is not SecretaryIntent.WRONG_NUMBER,
        approval_required=approval,
        approval_reason=("This communication involves a consequential or controlled action." if approval else "No consequential action is proposed."),
        escalation_required=escalation,
        escalation_reason=("Human review is required because the intent is high-risk, unknown, or the CRM match is ambiguous." if escalation else "No escalation is currently indicated."),
        draft_response=draft,
        decided_at=now or datetime.now(UTC),
    )
