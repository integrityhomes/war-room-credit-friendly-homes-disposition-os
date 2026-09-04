from datetime import UTC, datetime

import pytest

from cfh_disposition.commandcore_secretary_orchestrator import (
    CanonicalCommunicationEvent,
    CommunicationChannel,
    CommunicationDirection,
    SecretaryConfidence,
    SecretaryContactContext,
    SecretaryDealContext,
    SecretaryIntent,
    SecretaryPropertyContext,
    SecretaryRoutingConfiguration,
    SecretaryUrgency,
    decide_secretary_action,
)

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)
SENSITIVE_MESSAGE = "PRIVATE-MESSAGE-MUST-NOT-APPEAR-IN-DECISION"


def event(message: str, **updates: object) -> CanonicalCommunicationEvent:
    values: dict[str, object] = {
        "communication_event_id": "communication-event-1",
        "channel": CommunicationChannel.SMS,
        "direction": CommunicationDirection.INBOUND,
        "message_text": message,
    }
    values.update(updates)
    return CanonicalCommunicationEvent(**values)


def decide(message: str, **kwargs: object):
    return decide_secretary_action(event(message), now=NOW, **kwargs)


def test_known_seller_matches_existing_deal_property_and_owner() -> None:
    contact = SecretaryContactContext(
        contact_id="contact-1",
        phone="2175550100",
        relationship="Seller",
        assigned_worker="Contact Owner",
    )
    deal = SecretaryDealContext(
        deal_id="deal-1",
        contact_id="contact-1",
        property_id="property-1",
        assigned_worker="Current Deal Owner",
    )
    result = decide_secretary_action(
        event("Checking in for an update", contact_phone="(217) 555-0100"),
        contacts=(contact,),
        properties=(SecretaryPropertyContext(property_id="property-1"),),
        deals=(deal,),
        now=NOW,
    )
    assert result.matched_contact_id == "contact-1"
    assert result.matched_property_id == "property-1"
    assert result.matched_deal_id == "deal-1"
    assert result.intent is SecretaryIntent.EXISTING_SELLER_FOLLOW_UP
    assert result.suggested_owner == "Current Deal Owner"


def test_known_buyer_and_new_lead_intents() -> None:
    buyer = SecretaryContactContext(contact_id="buyer-1", relationship="Buyer")
    known = decide_secretary_action(
        event("Following up", contact_id="buyer-1"), contacts=(buyer,), now=NOW
    )
    assert known.intent is SecretaryIntent.EXISTING_BUYER_FOLLOW_UP
    assert decide("I want to sell my house").intent is SecretaryIntent.SELLER_LEAD
    assert decide("I am looking to buy a home").intent is SecretaryIntent.BUYER_LEAD


@pytest.mark.parametrize(
    ("message", "intent", "approval", "urgency"),
    [
        ("Can we schedule a showing?", SecretaryIntent.APPOINTMENT_REQUEST, False, SecretaryUrgency.PROMPT),
        ("What is the status of this deal?", SecretaryIntent.DEAL_QUESTION, False, SecretaryUrgency.PROMPT),
        ("Can you lower the price?", SecretaryIntent.OFFER_PRICE_DISCUSSION, True, SecretaryUrgency.HIGH),
        ("Where is my contract document?", SecretaryIntent.DOCUMENT_CONTRACT_QUESTION, True, SecretaryUrgency.HIGH),
        ("The title closing date changed", SecretaryIntent.TITLE_CLOSING, True, SecretaryUrgency.HIGH),
        ("I saw your Facebook listing", SecretaryIntent.MARKETING_DISPOSITION_RESPONSE, False, SecretaryUrgency.PROMPT),
        ("Send new bank payment instructions", SecretaryIntent.PAYMENT_MONEY, True, SecretaryUrgency.IMMEDIATE),
        ("My attorney says this is a legal issue", SecretaryIntent.LEGAL_COMPLIANCE, True, SecretaryUrgency.IMMEDIATE),
        ("This is a fraud complaint", SecretaryIntent.COMPLAINT_ESCALATION, True, SecretaryUrgency.IMMEDIATE),
        ("Wrong number", SecretaryIntent.WRONG_NUMBER, False, SecretaryUrgency.HIGH),
    ],
)
def test_initial_intents_and_high_risk_approval_gate(
    message: str,
    intent: SecretaryIntent,
    approval: bool,
    urgency: SecretaryUrgency,
) -> None:
    kwargs = {}
    if intent is SecretaryIntent.DEAL_QUESTION:
        kwargs = {
            "contacts": (SecretaryContactContext(contact_id="contact-1"),),
            "deals": (SecretaryDealContext(deal_id="deal-1", contact_id="contact-1"),),
        }
        result = decide_secretary_action(
            event(message, contact_id="contact-1"), now=NOW, **kwargs
        )
    else:
        result = decide(message)
    assert result.intent is intent
    assert result.approval_required is approval
    assert result.urgency is urgency
    assert result.prohibited_external_action is True
    if approval:
        assert result.escalation_required is True


def test_stop_consent_signal_has_priority_and_no_continued_response_draft() -> None:
    result = decide("STOP. I do not want payment information or another message.")
    assert result.intent is SecretaryIntent.CONSENT_STOP
    assert result.urgency is SecretaryUrgency.IMMEDIATE
    assert result.confidence is SecretaryConfidence.HIGH
    assert result.response_needed is False
    assert result.draft_response == ""
    assert result.task_needed is True
    assert result.approval_required is True


def test_ambiguous_identity_and_deal_fail_closed() -> None:
    contacts = (
        SecretaryContactContext(contact_id="contact-1", phone="2175550100"),
        SecretaryContactContext(contact_id="contact-2", phone="2175550100"),
    )
    ambiguous_identity = decide_secretary_action(
        event("I need an update", contact_phone="2175550100"),
        contacts=contacts,
        now=NOW,
    )
    assert ambiguous_identity.intent is SecretaryIntent.UNKNOWN
    assert ambiguous_identity.confidence is SecretaryConfidence.INSUFFICIENT
    assert ambiguous_identity.escalation_required is True

    contact = SecretaryContactContext(contact_id="contact-1")
    deals = (
        SecretaryDealContext(deal_id="deal-1", contact_id="contact-1"),
        SecretaryDealContext(deal_id="deal-2", contact_id="contact-1"),
    )
    ambiguous_deal = decide_secretary_action(
        event("What happens next?", contact_id="contact-1"),
        contacts=(contact,),
        deals=deals,
        now=NOW,
    )
    assert ambiguous_deal.matched_deal_id is None
    assert ambiguous_deal.confidence is SecretaryConfidence.INSUFFICIENT


def test_unknown_intent_and_routing_configuration_require_human_review() -> None:
    result = decide_secretary_action(
        event("Blue triangle", inbox="main-inbox"),
        routing=SecretaryRoutingConfiguration(
            inbox_owners={"main-inbox": "Configured Inbox Owner"}
        ),
        now=NOW,
    )
    assert result.intent is SecretaryIntent.UNKNOWN
    assert result.suggested_owner == "Configured Inbox Owner"
    assert result.escalation_required is True
    assert result.approval_required is False


def test_decision_is_reconstructable_but_suppresses_message_contents() -> None:
    result = decide(SENSITIVE_MESSAGE)
    payload = result.model_dump_json()
    assert result.communication_event_id == "communication-event-1"
    assert result.model_prompt_version == "commandcore-secretary-test-v1"
    assert result.model_provider == "Deterministic rules — no provider call"
    assert result.decided_at == NOW
    assert result.evidence
    assert SENSITIVE_MESSAGE not in payload
    assert "message_text" not in payload
    assert result.prohibited_external_action is True
