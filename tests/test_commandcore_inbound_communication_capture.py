from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = (ROOT / "supabase/functions/commandcore-inbound-communication-capture/index.ts").read_text(encoding="utf-8")


def test_existing_contact_and_deal_are_matched_before_safe_intake() -> None:
    match_position = CAPTURE.index("let matched = await matchExisting")
    intake_position = CAPTURE.index("const intake = await safeIntake")
    assert match_position < intake_position
    assert 'normalizePhone(item.phone) === phone' in CAPTURE
    assert 'text(links(item).contact_id) === contactId' in CAPTURE
    assert "const propertyId = text(links(matched.deal || {}).property_id);" in CAPTURE
    assert "property_id: propertyId || null" in CAPTURE
    assert "contacts.length !== 1" in CAPTURE
    assert "candidates.length === 1" in CAPTURE


def test_capture_consumes_the_provider_neutral_adapter_contract() -> None:
    assert "const eventCommunication = obj(event.communication);" in CAPTURE
    assert "const eventContactMatch = obj(event.contact_match);" in CAPTURE
    assert "const eventAttribution = obj(event.source_attribution);" in CAPTURE
    assert "normalizePhone(eventContactMatch.phone || event.contact_phone)" in CAPTURE
    assert "text(eventCommunication.recording_reference)" in CAPTURE
    assert "text(eventCommunication.transcript_reference)" in CAPTURE
    assert "source_attribution: eventAttribution" in CAPTURE


def test_unmatched_inbound_events_use_existing_safe_intake() -> None:
    assert '"commandcore-inbound-lead-capture"' in CAPTURE
    assert 'external_id: `phone-contact-${phone}`' in CAPTURE
    assert 'lead_type: "other"' in CAPTURE
    assert "const contactId = text(intake.contact_id);" in CAPTURE
    assert "const dealId = text(intake.deal_id);" in CAPTURE
    assert "unmatched_safe_intake_used: intakeUsed" in CAPTURE
    assert "!matched.ambiguous" in CAPTURE


def test_existing_crm_entities_are_the_only_history_and_task_store() -> None:
    for entity in ("communications", "activities", "tasks"):
        assert f'upsertCrm(supabaseUrl, serviceKey, "{entity}"' in CAPTURE
    assert 'external_id: `phone-event-${eventId}`' in CAPTURE
    assert 'external_id: `phone-activity-${eventId}`' in CAPTURE
    assert 'external_id: `phone-follow-up-${eventId}`' in CAPTURE


def test_follow_up_is_limited_and_preserves_deal_owner() -> None:
    for event_type in (
        "communication.sms.received",
        "communication.call.missed",
        "communication.voicemail.received",
    ):
        assert event_type in CAPTURE
    assert "if (FOLLOW_UP_EVENTS.has(eventType) && dealId)" in CAPTURE
    assert "const dealOwner = text(matched.deal?.assigned_to);" in CAPTURE
    assert "assigned_to: dealOwner || null" in CAPTURE
    assert "owner_preserved: Boolean(dealOwner)" in CAPTURE


def test_consent_and_suppression_are_preserved_without_sending() -> None:
    assert '"commandcore-contact-ledger"' in CAPTURE
    assert 'action: "evaluate_contact"' in CAPTURE
    assert "Contact is suppressed; do not send an outbound response" in CAPTURE
    assert "consent_review_required:" in CAPTURE
    assert "outbound_calls: 0" in CAPTURE
    assert "outbound_messages: 0" in CAPTURE
    assert CAPTURE.count("external_action_started: false") >= 8
    for forbidden in ("sendSms", "sendMessage", "makeCall", "openphone.com", "oauth", "access_token:"):
        assert forbidden not in CAPTURE
    assert "console.error" not in CAPTURE


def test_capture_fails_closed_before_processing() -> None:
    auth = CAPTURE.index("if (!isAuthenticated(req))")
    parse = CAPTURE.index("body = JSON.parse")
    match = CAPTURE.index("let matched = await matchExisting")
    assert auth < parse < match
    for error in ("unauthorized", "payload_too_large", "invalid_json", "communication_event_identity_required", "contact_phone_required"):
        assert error in CAPTURE
