from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConversationState(StrEnum):
    AI_HANDLING = "AI Handling"
    VA_HANDLING = "VA Handling"
    WAITING_ON_CUSTOMER = "Waiting on Customer"
    NEEDS_HUMAN = "Needs Human"
    AI_CAN_RESUME = "AI Can Resume"
    PAUSED = "Paused"


class ConversationActor(StrEnum):
    CUSTOMER = "Customer"
    AI_DRAFT = "AI Draft"
    AI = "AI"
    VA = "VA"


class HandoffAction(StrEnum):
    TAKE_OVER = "Take Over"
    HAND_BACK_TO_AI = "Hand Back to AI"
    PAUSE_AI = "Pause AI"
    ASK_AI_TO_CONTINUE = "Ask AI to Continue"
    CUSTOMER_REQUESTED_PERSON = "Customer Requested Person"
    WAIT_FOR_CUSTOMER = "Wait for Customer"


class EscalationReason(StrEnum):
    UNKNOWN_ANSWER = "Answer is not known"
    LEGAL_INTERPRETATION = "Legal interpretation requested"
    CONTRACT_CHANGE = "Contract terms may change"
    FINANCING_CHANGE = "Financing terms may change"
    NEGOTIATION = "Consequential negotiation requested"
    PAYMENT_OR_BANKING = "Payment or bank information involved"
    SIGNATURE_OR_AGREEMENT = "Signature or binding agreement involved"
    CUSTOMER_REQUESTED_PERSON = "Customer requested a person"
    LOW_CONFIDENCE = "Answer confidence is insufficient"
    POLICY_REVIEW = "Company policy requires human review"


class PropertyAvailability(StrEnum):
    AVAILABLE = "Available"
    PENDING = "Pending"
    SOLD_UNAVAILABLE = "Sold / Unavailable"
    PAUSED = "Paused"
    COMING_SOON = "Coming Soon"


class LearningSignal(StrEnum):
    VA_CORRECTION = "VA correction"
    VA_EDIT = "VA edit"
    TAKEOVER = "VA takeover"
    RECURRING_UNANSWERED_QUESTION = "Recurring unanswered question"
    APPROVED_USEFUL_WORDING = "Approved useful wording"


class LearningRisk(StrEnum):
    NORMAL_OPERATIONAL = "Normal operational"
    RESTRICTED = "Restricted"


RESTRICTED_LEARNING_CATEGORIES = {
    "legal interpretation",
    "contract",
    "property fact",
    "price",
    "pricing",
    "financing term",
    "company policy",
    "fair housing",
    "compliance rule",
    "consequential decision",
}


class AnsweredQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_key: str = Field(min_length=1, max_length=160)
    question_text: str = Field(min_length=1, max_length=1000)
    answer_summary: str = Field(min_length=1, max_length=2000)
    extracted_facts: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    supporting_communication_ids: list[str] = Field(min_length=1)


class ConversationMemory(BaseModel):
    """A derived operational projection; CRM Communications remain authoritative."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_id: str = Field(min_length=1, max_length=200)
    deal_id: str = Field(min_length=1, max_length=200)
    preferred_language: str = "Uncertain"
    customer_goal: str = ""
    property_or_market_interest: str = ""
    budget: str = ""
    down_payment: str = ""
    desired_monthly_payment: str = ""
    bedrooms: str = ""
    bathrooms: str = ""
    showing_availability: str = ""
    answered_questions: list[AnsweredQuestion] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    last_meaningful_customer_question: str = ""
    next_permitted_question_or_action: str = ""
    current_handler: ConversationState = ConversationState.AI_HANDLING
    source_communication_ids: list[str] = Field(default_factory=list)
    derived_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    overwrites_original_communications: bool = False
    property_facts_are_authoritative: bool = False

    @model_validator(mode="after")
    def preserve_authoritative_history(self) -> ConversationMemory:
        if self.overwrites_original_communications:
            raise ValueError("Derived memory may not overwrite original CRM Communications")
        if self.property_facts_are_authoritative:
            raise ValueError("Conversation memory cannot be authoritative for property facts")
        supported = {item for answer in self.answered_questions for item in answer.supporting_communication_ids}
        if not supported.issubset(set(self.source_communication_ids)):
            raise ValueError("Every answered question must reference a source CRM Communication")
        return self

    def has_answer(self, question_key: str) -> bool:
        normalized = question_key.strip().casefold()
        return any(item.question_key.casefold() == normalized for item in self.answered_questions)


class SharedConversationTurn(BaseModel):
    """Reference to one authoritative CRM Communication shared by the AI and VA."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    crm_communication_id: str = Field(min_length=1, max_length=200)
    contact_id: str = Field(min_length=1, max_length=200)
    deal_id: str = Field(min_length=1, max_length=200)
    actor: ConversationActor
    original_text: str
    language: str
    english_va_summary: str = ""
    persisted_to_crm_communications: bool = True
    external_action_started: bool = False

    @model_validator(mode="after")
    def require_shared_history(self) -> SharedConversationTurn:
        if not self.persisted_to_crm_communications:
            raise ValueError("Every AI and VA turn must be stored in CRM Communications")
        if self.external_action_started:
            raise ValueError("The Secretary foundation cannot start an external action")
        return self


class ConversationControl(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact_id: str
    deal_id: str
    state: ConversationState = ConversationState.AI_HANDLING
    assigned_worker: str = ""
    last_ai_seen_communication_id: str = ""
    newer_communication_ids: list[str] = Field(default_factory=list)
    ai_reply_generation_allowed: bool = True
    external_action_started: bool = False

    @model_validator(mode="after")
    def enforce_state_safety(self) -> ConversationControl:
        should_allow = self.state in {ConversationState.AI_HANDLING, ConversationState.AI_CAN_RESUME}
        if self.ai_reply_generation_allowed != should_allow:
            raise ValueError("AI reply permission must match the conversation-control state")
        if self.external_action_started:
            raise ValueError("The Secretary foundation cannot start an external action")
        if self.state == ConversationState.NEEDS_HUMAN and not self.assigned_worker:
            raise ValueError("Needs Human requires the existing assigned Deal owner or worker")
        return self


def transition_conversation(
    control: ConversationControl,
    action: HandoffAction,
    *,
    reread_communication_ids: Sequence[str] = (),
) -> ConversationControl:
    state = control.state
    last_seen = control.last_ai_seen_communication_id
    newer = list(control.newer_communication_ids)
    if action == HandoffAction.TAKE_OVER:
        state = ConversationState.VA_HANDLING
    elif action == HandoffAction.PAUSE_AI:
        state = ConversationState.PAUSED
    elif action == HandoffAction.CUSTOMER_REQUESTED_PERSON:
        state = ConversationState.NEEDS_HUMAN
    elif action == HandoffAction.WAIT_FOR_CUSTOMER:
        state = ConversationState.WAITING_ON_CUSTOMER
    elif action in {HandoffAction.HAND_BACK_TO_AI, HandoffAction.ASK_AI_TO_CONTINUE}:
        reread = list(reread_communication_ids)
        if not set(newer).issubset(set(reread)):
            raise ValueError("AI must reread every newer CRM Communication before continuing")
        if newer:
            last_seen = newer[-1]
        newer = []
        state = ConversationState.AI_CAN_RESUME
    return control.model_copy(
        update={
            "state": state,
            "last_ai_seen_communication_id": last_seen,
            "newer_communication_ids": newer,
            "ai_reply_generation_allowed": state in {ConversationState.AI_HANDLING, ConversationState.AI_CAN_RESUME},
        }
    )


class VerifiedPropertyFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    property_id: str
    availability: PropertyAvailability
    verified_at: datetime
    source_record_version: str
    facts_verified: bool
    address: str = ""
    price: str = ""
    down_payment: str = ""
    monthly_payment: str = ""
    financing_terms: str = ""
    condition: str = ""


class VerifiedPropertyInventory(Protocol):
    """Read-only boundary for current CommandCore inventory; no Google connector exists yet."""

    def get_verified_property(self, property_id: str) -> VerifiedPropertyFacts | None: ...

    def similar_available_properties(self, property_id: str) -> Sequence[VerifiedPropertyFacts]: ...


def require_verified_property(inventory: VerifiedPropertyInventory, property_id: str) -> VerifiedPropertyFacts:
    facts = inventory.get_verified_property(property_id)
    if facts is None or not facts.facts_verified or not facts.source_record_version:
        raise ValueError("Current verified CommandCore property facts are unavailable")
    return facts


def available_alternatives(inventory: VerifiedPropertyInventory, property_id: str) -> tuple[VerifiedPropertyFacts, ...]:
    current = require_verified_property(inventory, property_id)
    if current.availability == PropertyAvailability.AVAILABLE:
        return ()
    return tuple(
        item
        for item in inventory.similar_available_properties(property_id)
        if item.facts_verified and item.availability == PropertyAvailability.AVAILABLE
    )


class SecretaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state: ConversationState
    assigned_worker: str = ""
    draft_reply_allowed: bool = False
    automated_outbound_authorized: bool = False
    spanish_compliance_equivalence_verified: bool = False
    escalation_reason: EscalationReason | None = None
    create_existing_follow_up_task: bool = False
    next_step: str
    external_action_started: bool = False

    @model_validator(mode="after")
    def enforce_foundation_safety(self) -> SecretaryDecision:
        if self.automated_outbound_authorized or self.external_action_started:
            raise ValueError("The Secretary foundation cannot authorize or start outbound communication")
        if self.spanish_compliance_equivalence_verified:
            raise ValueError("Spanish compliance equivalence requires a later approved build")
        if self.state == ConversationState.NEEDS_HUMAN and not self.create_existing_follow_up_task:
            raise ValueError("Needs Human must create work in the existing follow-up system")
        return self


def needs_human_decision(reason: EscalationReason, *, assigned_worker: str) -> SecretaryDecision:
    return SecretaryDecision(
        state=ConversationState.NEEDS_HUMAN,
        assigned_worker=assigned_worker,
        escalation_reason=reason,
        create_existing_follow_up_task=True,
        next_step="Route this conversation to the currently assigned Deal owner or worker for review.",
    )


class LearningCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_id: str
    signal: LearningSignal
    category: str
    language: str
    proposed_wording: str
    reason: str
    source_communication_ids: list[str] = Field(min_length=1)
    risk: LearningRisk = LearningRisk.NORMAL_OPERATIONAL
    review_status: str = "Pending review"
    reviewed_by: str = ""
    approved_knowledge_version: str = ""
    rollback_version: str = ""
    automatically_promoted: bool = False

    @model_validator(mode="after")
    def require_review_and_block_restricted_promotion(self) -> LearningCandidate:
        category = self.category.casefold()
        restricted = any(item in category for item in RESTRICTED_LEARNING_CATEGORIES)
        if self.automatically_promoted:
            raise ValueError("Learning candidates may never promote themselves")
        if restricted and self.risk != LearningRisk.RESTRICTED:
            raise ValueError("Restricted knowledge must be classified as restricted")
        if self.review_status == "Approved" and (
            not self.reviewed_by or not self.approved_knowledge_version or not self.rollback_version
        ):
            raise ValueError("Approved knowledge requires reviewer, version, and rollback information")
        return self


class SecretaryQualityScorecard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversations_handled_without_human: int = Field(default=0, ge=0)
    repeat_question_count: int = Field(default=0, ge=0)
    incorrect_answer_or_correction_count: int = Field(default=0, ge=0)
    escalation_count: int = Field(default=0, ge=0)
    average_response_seconds: float | None = Field(default=None, ge=0)
    english_conversations: int = Field(default=0, ge=0)
    spanish_conversations: int = Field(default=0, ge=0)
    appointments_or_showings_created: int = Field(default=0, ge=0)
    va_takeover_count: int = Field(default=0, ge=0)
    unanswered_question_categories: Mapping[str, int] = Field(default_factory=dict)
    production_analytics_connected: bool = False

    @model_validator(mode="after")
    def keep_analytics_offline(self) -> SecretaryQualityScorecard:
        if self.production_analytics_connected:
            raise ValueError("Production analytics are outside the Secretary foundation")
        return self


GOOGLE_SHEET_INVENTORY_NEXT_BUILD = (
    "Google Sheet → validated CommandCore property synchronization is required before live Secretary property answering."
)
