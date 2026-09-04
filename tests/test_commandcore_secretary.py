from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from cfh_disposition.commandcore_secretary import (
    GOOGLE_SHEET_INVENTORY_NEXT_BUILD,
    AnsweredQuestion,
    ConversationActor,
    ConversationControl,
    ConversationMemory,
    ConversationState,
    EscalationReason,
    HandoffAction,
    LearningCandidate,
    LearningRisk,
    LearningSignal,
    PropertyAvailability,
    SecretaryDecision,
    SecretaryQualityScorecard,
    SharedConversationTurn,
    VerifiedPropertyFacts,
    available_alternatives,
    needs_human_decision,
    require_verified_property,
    transition_conversation,
)


def control(**updates: object) -> ConversationControl:
    values: dict[str, object] = {"contact_id": "contact-1", "deal_id": "deal-1", "assigned_worker": "Assigned Team Member"}
    values.update(updates)
    return ConversationControl(**values)


def test_takeover_pause_and_customer_request_stop_ai() -> None:
    for action, state in (
        (HandoffAction.TAKE_OVER, ConversationState.VA_HANDLING),
        (HandoffAction.PAUSE_AI, ConversationState.PAUSED),
        (HandoffAction.CUSTOMER_REQUESTED_PERSON, ConversationState.NEEDS_HUMAN),
        (HandoffAction.WAIT_FOR_CUSTOMER, ConversationState.WAITING_ON_CUSTOMER),
    ):
        result = transition_conversation(control(), action)
        assert result.state == state
        assert result.ai_reply_generation_allowed is False
        assert result.assigned_worker == "Assigned Team Member"


def test_ai_and_va_turns_must_share_authoritative_crm_history() -> None:
    for actor in (ConversationActor.AI, ConversationActor.VA, ConversationActor.CUSTOMER):
        turn = SharedConversationTurn(
            crm_communication_id=f"comm-{actor.value}",
            contact_id="contact-1",
            deal_id="deal-1",
            actor=actor,
            original_text="Exact original message",
            language="English",
        )
        assert turn.persisted_to_crm_communications is True
        assert turn.external_action_started is False
    with pytest.raises(ValidationError, match="stored in CRM Communications"):
        SharedConversationTurn(
            crm_communication_id="comm-draft",
            contact_id="contact-1",
            deal_id="deal-1",
            actor=ConversationActor.AI_DRAFT,
            original_text="Internal draft",
            language="Spanish",
            persisted_to_crm_communications=False,
        )


def test_hand_back_requires_every_newer_crm_communication_to_be_read() -> None:
    taken_over = control(
        state=ConversationState.VA_HANDLING,
        ai_reply_generation_allowed=False,
        newer_communication_ids=["comm-2", "comm-3"],
    )
    with pytest.raises(ValueError, match="reread every newer CRM Communication"):
        transition_conversation(taken_over, HandoffAction.HAND_BACK_TO_AI, reread_communication_ids=["comm-3"])
    resumed = transition_conversation(
        taken_over,
        HandoffAction.HAND_BACK_TO_AI,
        reread_communication_ids=["comm-2", "comm-3"],
    )
    assert resumed.state == ConversationState.AI_CAN_RESUME
    assert resumed.last_ai_seen_communication_id == "comm-3"
    assert resumed.newer_communication_ids == []
    assert resumed.ai_reply_generation_allowed is True


def test_memory_prevents_repeat_questions_and_preserves_source_history() -> None:
    answer = AnsweredQuestion(
        question_key="desired-monthly-payment",
        question_text="What monthly payment works for you?",
        answer_summary="Customer stated a preferred range.",
        extracted_facts={"desired_monthly_payment": "Customer-provided range"},
        supporting_communication_ids=["comm-1"],
    )
    memory = ConversationMemory(
        contact_id="contact-1",
        deal_id="deal-1",
        answered_questions=[answer],
        source_communication_ids=["comm-1"],
        last_meaningful_customer_question="Which homes are available?",
        unresolved_questions=["Current property availability"],
        next_permitted_question_or_action="Query verified CommandCore inventory.",
    )
    assert memory.has_answer("DESIRED-MONTHLY-PAYMENT")
    assert memory.overwrites_original_communications is False
    assert memory.property_facts_are_authoritative is False
    with pytest.raises(ValidationError, match="source CRM Communication"):
        memory.model_copy(update={"source_communication_ids": []}).model_validate(
            memory.model_copy(update={"source_communication_ids": []}).model_dump()
        )
    with pytest.raises(ValidationError, match="cannot be authoritative for property facts"):
        ConversationMemory(
            contact_id="contact-1",
            deal_id="deal-1",
            property_facts_are_authoritative=True,
        )


class Inventory:
    def __init__(self, current: VerifiedPropertyFacts | None, alternatives: list[VerifiedPropertyFacts] | None = None):
        self.current = current
        self.alternatives = alternatives or []

    def get_verified_property(self, property_id: str) -> VerifiedPropertyFacts | None:
        return self.current if self.current and self.current.property_id == property_id else None

    def similar_available_properties(self, property_id: str) -> list[VerifiedPropertyFacts]:
        return self.alternatives


def property_facts(property_id: str, availability: PropertyAvailability, *, verified: bool = True) -> VerifiedPropertyFacts:
    return VerifiedPropertyFacts(
        property_id=property_id,
        availability=availability,
        verified_at=datetime.now(UTC),
        source_record_version="inventory-v1",
        facts_verified=verified,
        price="$100,000",
        down_payment="$10,000",
        monthly_payment="$1,000",
    )


def test_property_answers_require_current_verified_inventory() -> None:
    with pytest.raises(ValueError, match="verified CommandCore property facts"):
        require_verified_property(Inventory(None), "property-1")
    with pytest.raises(ValueError, match="verified CommandCore property facts"):
        require_verified_property(Inventory(property_facts("property-1", PropertyAvailability.AVAILABLE, verified=False)), "property-1")
    facts = require_verified_property(Inventory(property_facts("property-1", PropertyAvailability.AVAILABLE)), "property-1")
    assert facts.monthly_payment == "$1,000"
    assert "Google Sheet" in GOOGLE_SHEET_INVENTORY_NEXT_BUILD
    assert "required before live Secretary property answering" in GOOGLE_SHEET_INVENTORY_NEXT_BUILD


def test_unavailable_property_returns_only_verified_available_alternatives() -> None:
    current = property_facts("property-1", PropertyAvailability.SOLD_UNAVAILABLE)
    available = property_facts("property-2", PropertyAvailability.AVAILABLE)
    pending = property_facts("property-3", PropertyAvailability.PENDING)
    unverified = property_facts("property-4", PropertyAvailability.AVAILABLE, verified=False)
    assert available_alternatives(Inventory(current, [available, pending, unverified]), "property-1") == (available,)


@pytest.mark.parametrize("reason", list(EscalationReason))
def test_all_consequential_or_uncertain_reasons_create_existing_human_work(reason: EscalationReason) -> None:
    decision = needs_human_decision(reason, assigned_worker="Current Deal Owner")
    assert decision.state == ConversationState.NEEDS_HUMAN
    assert decision.assigned_worker == "Current Deal Owner"
    assert decision.create_existing_follow_up_task is True
    assert decision.automated_outbound_authorized is False
    assert decision.external_action_started is False


def test_spanish_and_all_other_automated_outbound_remain_unauthorized() -> None:
    decision = SecretaryDecision(state=ConversationState.AI_HANDLING, draft_reply_allowed=True, next_step="Internal review only")
    assert decision.spanish_compliance_equivalence_verified is False
    assert decision.automated_outbound_authorized is False
    with pytest.raises(ValidationError, match="later approved build"):
        SecretaryDecision(
            state=ConversationState.AI_HANDLING,
            spanish_compliance_equivalence_verified=True,
            next_step="Not allowed",
        )
    with pytest.raises(ValidationError, match="cannot authorize"):
        SecretaryDecision(state=ConversationState.AI_HANDLING, automated_outbound_authorized=True, next_step="Not allowed")


def test_needs_human_requires_existing_assignment() -> None:
    with pytest.raises(ValidationError, match="assigned Deal owner or worker"):
        ConversationControl(
            contact_id="contact-1",
            deal_id="deal-1",
            state=ConversationState.NEEDS_HUMAN,
            ai_reply_generation_allowed=False,
        )


@pytest.mark.parametrize(
    "category",
    ["legal interpretation", "contract", "property fact", "pricing", "financing term", "company policy", "fair housing", "compliance rule", "consequential decision"],
)
def test_restricted_learning_can_be_queued_but_not_self_promoted(category: str) -> None:
    candidate = LearningCandidate(
        candidate_id="candidate-1",
        signal=LearningSignal.VA_CORRECTION,
        category=category,
        language="English",
        proposed_wording="Review-only candidate",
        reason="A VA correction created this candidate.",
        source_communication_ids=["comm-1"],
        risk=LearningRisk.RESTRICTED,
    )
    assert candidate.review_status == "Pending review"
    with pytest.raises(ValidationError, match="never promote themselves"):
        candidate.model_copy(update={"automatically_promoted": True}).model_validate(
            candidate.model_copy(update={"automatically_promoted": True}).model_dump()
        )


def test_approved_learning_requires_version_and_rollback() -> None:
    values = {
        "candidate_id": "candidate-2",
        "signal": LearningSignal.APPROVED_USEFUL_WORDING,
        "category": "greeting clarity",
        "language": "Spanish",
        "proposed_wording": "Review-only wording",
        "reason": "Approved VA wording resolved a recurring question.",
        "source_communication_ids": ["comm-2"],
        "review_status": "Approved",
        "reviewed_by": "Knowledge Reviewer",
    }
    with pytest.raises(ValidationError, match="version, and rollback"):
        LearningCandidate(**values)
    approved = LearningCandidate(**values, approved_knowledge_version="v2", rollback_version="v1")
    assert approved.approved_knowledge_version == "v2"


def test_quality_scorecard_is_design_only() -> None:
    scorecard = SecretaryQualityScorecard(english_conversations=4, spanish_conversations=2, va_takeover_count=1)
    assert scorecard.production_analytics_connected is False
    with pytest.raises(ValidationError, match="outside the Secretary foundation"):
        SecretaryQualityScorecard(production_analytics_connected=True)
