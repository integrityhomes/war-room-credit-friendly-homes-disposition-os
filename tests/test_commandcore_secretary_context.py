from cfh_disposition.commandcore_secretary_context import (
    ConsentReadState,
    MatchQuality,
    evaluate_commandcore_communication,
    safe_communication_label,
)
from cfh_disposition.commandcore_secretary_orchestrator import (
    SecretaryConfidence,
    SecretaryIntent,
    SecretaryRoutingConfiguration,
)

SENSITIVE = "PRIVATE-MESSAGE-MUST-NOT-LEAK"


def communication(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "communication-1",
        "channel": "sms",
        "direction": "inbound",
        "body": "Can we schedule a showing?",
        "created_at": "2026-09-04T12:00:00Z",
        "links": {"contact_id": "contact-1"},
    }
    record.update(updates)
    return record


def contact(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "contact-1",
        "name": "Test Seller",
        "contact_type": "Seller",
        "phone": "2175550100",
        "assigned_to": "Contact Owner",
        "sms_consent": True,
    }
    record.update(updates)
    return record


def property_(**updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "property-1",
        "address": "101 Example Avenue",
    }
    record.update(updates)
    return record


def deal(identifier: str = "deal-1", **updates: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": identifier,
        "title": "Example Deal",
        "status": "Active",
        "assigned_to": "Existing Deal Owner",
        "links": {"contact_id": "contact-1", "property_id": "property-1"},
    }
    record.update(updates)
    return record


def evaluate(comm: dict[str, object], **updates: object):
    values = {
        "contacts": (contact(),),
        "properties": (property_(),),
        "deals": (deal(),),
    }
    values.update(updates)
    return evaluate_commandcore_communication(comm, **values)


def test_real_event_exact_contact_and_one_active_deal_routes_to_deal_owner() -> None:
    result = evaluate(communication())
    assert result.decision.matched_contact_id == "contact-1"
    assert result.decision.matched_deal_id == "deal-1"
    assert result.decision.matched_property_id == "property-1"
    assert result.match_quality.contact is MatchQuality.EXACT
    assert result.match_quality.deal is MatchQuality.EXACT_RELATIONSHIP
    assert result.match_quality.property is MatchQuality.EXACT_RELATIONSHIP
    assert result.match_quality.routing_source == "Existing deal owner"
    assert result.decision.suggested_owner == "Existing Deal Owner"
    assert result.consent_state is ConsentReadState.CONSENT_RECORDED


def test_exact_contact_prefers_one_unambiguous_active_deal() -> None:
    closed = deal("deal-closed", status="Closed")
    active = deal("deal-active")
    result = evaluate(communication(), deals=(closed, active))
    assert result.decision.matched_deal_id == "deal-active"
    assert result.match_quality.deal is MatchQuality.ONE_ACTIVE_DEAL


def test_contact_with_multiple_active_deals_fails_closed() -> None:
    result = evaluate(communication(), deals=(deal("deal-1"), deal("deal-2")))
    assert result.decision.matched_deal_id is None
    assert result.match_quality.deal is MatchQuality.AMBIGUOUS
    assert result.decision.confidence is SecretaryConfidence.INSUFFICIENT
    assert result.decision.escalation_required is True


def test_explicit_deal_is_first_priority_and_derives_contact_property() -> None:
    comm = communication(links={"deal_id": "deal-2"})
    selected = deal("deal-2")
    result = evaluate(comm, deals=(deal("deal-1"), selected))
    assert result.decision.matched_deal_id == "deal-2"
    assert result.decision.matched_contact_id == "contact-1"
    assert result.decision.matched_property_id == "property-1"
    assert result.match_quality.deal is MatchQuality.EXACT


def test_property_linked_deal_resolves_without_guessing() -> None:
    comm = communication(links={"property_id": "property-1"})
    result = evaluate(comm)
    assert result.match_quality.property is MatchQuality.EXACT
    assert result.match_quality.deal is MatchQuality.EXACT_RELATIONSHIP
    assert result.decision.matched_deal_id == "deal-1"


def test_seller_and_buyer_use_existing_deal_owner_not_hard_coded_names() -> None:
    seller = evaluate(communication(body="Following up"))
    buyer = evaluate(
        communication(body="Following up"),
        contacts=(contact(contact_type="Buyer"),),
    )
    assert seller.decision.intent is SecretaryIntent.EXISTING_SELLER_FOLLOW_UP
    assert buyer.decision.intent is SecretaryIntent.EXISTING_BUYER_FOLLOW_UP
    assert seller.decision.suggested_owner == buyer.decision.suggested_owner == "Existing Deal Owner"


def test_missing_worker_fails_closed_and_configured_fallbacks_are_explicit() -> None:
    unowned_contact = contact(assigned_to="")
    unowned_deal = deal(assigned_to="")
    missing = evaluate(communication(), contacts=(unowned_contact,), deals=(unowned_deal,))
    assert missing.match_quality.routing_source == "Management review"
    assert missing.decision.confidence is SecretaryConfidence.INSUFFICIENT

    inbox = evaluate_commandcore_communication(
        communication(inbox="seller-inbox"),
        contacts=(unowned_contact,),
        properties=(property_(),),
        deals=(unowned_deal,),
        routing=SecretaryRoutingConfiguration(inbox_owners={"seller-inbox": "Inbox Owner"}),
    )
    assert inbox.decision.suggested_owner == "Inbox Owner"
    assert inbox.match_quality.routing_source == "Configured inbox owner"

    channel = evaluate_commandcore_communication(
        communication(),
        contacts=(unowned_contact,),
        properties=(property_(),),
        deals=(unowned_deal,),
        routing=SecretaryRoutingConfiguration(channel_owners={"SMS": "SMS Team"}),
    )
    assert channel.decision.suggested_owner == "SMS Team"
    assert channel.match_quality.routing_source == "Configured channel owner"


def test_stop_and_payment_use_existing_context_and_controlled_handling() -> None:
    stopped = evaluate(
        communication(body="STOP"),
        contacts=(contact(do_not_contact=True),),
    )
    assert stopped.decision.intent is SecretaryIntent.CONSENT_STOP
    assert stopped.consent_state is ConsentReadState.DO_NOT_CONTACT
    assert stopped.decision.draft_response == ""
    payment = evaluate(communication(body="Change my bank payment instructions"))
    assert payment.decision.intent is SecretaryIntent.PAYMENT_MONEY
    assert payment.decision.approval_required is True
    assert payment.decision.matched_deal_id == "deal-1"


def test_existing_contact_ledger_consent_snapshot_is_read_without_mutation() -> None:
    opted_out = evaluate_commandcore_communication(
        communication(body="STOP"),
        contacts=(contact(sms_consent=True),),
        properties=(property_(),),
        deals=(deal(),),
        consent_record={
            "sms_consent_state": "opt_out",
            "email_consent_state": "unknown",
            "suppressed": True,
        },
    )
    assert opted_out.consent_state is ConsentReadState.SUPPRESSED
    assert opted_out.consent_mutations == 0

    granted = evaluate_commandcore_communication(
        communication(),
        contacts=(contact(sms_consent=False),),
        properties=(property_(),),
        deals=(deal(),),
        consent_record={
            "sms_consent_state": "granted",
            "email_consent_state": "unknown",
            "suppressed": False,
        },
    )
    assert granted.consent_state is ConsentReadState.CONSENT_RECORDED


def test_ambiguous_contact_property_and_deal_each_fail_closed() -> None:
    ambiguous_contact = evaluate_commandcore_communication(
        communication(links={}, phone="2175550100"),
        contacts=(contact(), contact(id="contact-2")),
        properties=(),
        deals=(),
    )
    assert ambiguous_contact.match_quality.contact is MatchQuality.AMBIGUOUS
    assert ambiguous_contact.decision.confidence is SecretaryConfidence.INSUFFICIENT

    ambiguous_property = evaluate_commandcore_communication(
        communication(links={"contact_id": "contact-1"}, property_address="101 Example Avenue"),
        contacts=(contact(),),
        properties=(property_(), property_(id="property-2")),
        deals=(),
    )
    assert ambiguous_property.match_quality.property is MatchQuality.AMBIGUOUS
    assert ambiguous_property.decision.confidence is SecretaryConfidence.INSUFFICIENT

    ambiguous_deal = evaluate(communication(), deals=(deal("deal-1"), deal("deal-2")))
    assert ambiguous_deal.match_quality.deal is MatchQuality.AMBIGUOUS


def test_read_only_result_has_zero_mutations_and_suppresses_message_content() -> None:
    comm = communication(body=SENSITIVE)
    result = evaluate(comm)
    serialized = result.model_dump_json()
    assert result.records_written == 0
    assert result.tasks_created == 0
    assert result.consent_mutations == 0
    assert result.external_actions_started == 0
    assert result.decision.prohibited_external_action is True
    assert SENSITIVE not in serialized
    assert "body" not in serialized


def test_selection_label_excludes_message_phone_and_email() -> None:
    comm = communication(body=SENSITIVE, phone="2175550100", email="private@example.invalid")
    label = safe_communication_label(comm, (contact(),))
    assert "2026-09-04" in label
    assert "SMS" in label
    assert "Test Seller" in label
    assert SENSITIVE not in label
    assert "2175550100" not in label
    assert "private@example.invalid" not in label
