from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = (ROOT / "supabase/functions/commandcore-inbound-communication-capture/index.ts").read_text(encoding="utf-8")


def test_capture_accepts_provider_neutral_inbound_email_sms_and_facebook_fields() -> None:
    for marker in (
        "event.provider || event.source || attribution.source",
        "event.external_message_id",
        "communication.channel || event.channel",
        "communication.message_text || communication.body || communication.summary",
        "event.received_at || event.occurred_at",
        "event.sender_identifier",
        "event.recipient_identifier",
        'direction: "inbound"',
    ):
        assert marker in CAPTURE
    for channel in ("email", "sms", "facebook"):
        assert channel not in {"unsupported", "blocked"}


def test_only_existing_commandcore_communications_are_written() -> None:
    assert 'crmRequest(url, key, "upsert", "communications", { record })' in CAPTURE
    assert "communication_write_only: true" in CAPTURE
    assert "canonical_communications_store: true" in CAPTURE
    for forbidden in (
        '"upsert", "contacts"',
        '"upsert", "properties"',
        '"upsert", "deals"',
        '"upsert", "activities"',
        '"upsert", "tasks"',
        "commandcore-inbound-lead-capture",
        "safeIntake",
    ):
        assert forbidden not in CAPTURE
    for result in (
        "contact_mutations: 0",
        "deal_mutations: 0",
        "property_mutations: 0",
        "activities_created: 0",
        "tasks_created: 0",
        "consent_mutations: 0",
    ):
        assert result in CAPTURE


def test_deduplication_uses_stable_source_message_identity_and_crm_upsert() -> None:
    assert "const deduplicationKey = `${source}:${externalMessageId}`.toLowerCase();" in CAPTURE
    assert "text(item.external_id).toLowerCase() === deduplicationKey" in CAPTURE
    assert "duplicate_ignored: alreadyCaptured" in CAPTURE
    assert "external_id: deduplicationKey" in CAPTURE
    assert "replay_safe: true" in CAPTURE


def test_contact_matching_is_exact_or_fails_to_human_review() -> None:
    for marker in (
        "event.contact_id || match.contact_id",
        "match.external_contact_reference",
        "normalizePhone(item.phone) === phone",
        "normalizeEmail(item.email) === email",
        "if (candidates.length > 1)",
        '"needs_human_review"',
    ):
        assert marker in CAPTURE


def test_deal_property_context_is_attached_only_when_unambiguous() -> None:
    assert "const explicitDealId" in CAPTURE
    assert "const explicitPropertyId" in CAPTURE
    assert "if (choices.length > 1)" in CAPTURE
    assert "if (linkedPropertyId && !property)" in CAPTURE
    assert "contact_id: contactId || null" in CAPTURE
    assert "property_id: propertyId || null" in CAPTURE
    assert "deal_id: dealId || null" in CAPTURE
    assert "assigned_to: assignedWorker || null" in CAPTURE


def test_stop_is_visible_without_consent_mutation_or_response() -> None:
    assert "function isStopRequest" in CAPTURE
    assert "consent_stop_indicated: stopRequested" in CAPTURE
    assert 'priority: stopRequested ? "immediate" : "unreviewed"' in CAPTURE
    assert "consent_mutations: 0" in CAPTURE
    assert "outbound_messages: 0" in CAPTURE
    assert "outbound_calls: 0" in CAPTURE


def test_capture_is_inbound_only_and_cannot_execute_external_actions() -> None:
    assert 'if (direction !== "inbound")' in CAPTURE
    assert 'error: "inbound_only"' in CAPTURE
    assert 'error: "external_action_prohibited"' in CAPTURE
    assert CAPTURE.count("external_action_started: false") >= 8
    for forbidden in ("sendSms", "sendEmail", "sendMessage", "makeCall", "Deno.connect", "oauth"):
        assert forbidden not in CAPTURE


def test_canonical_record_keeps_required_ingestion_and_cost_metadata() -> None:
    for marker in (
        "communication_event_id: eventId",
        "external_message_id: externalMessageId",
        "ingestion_timestamp: new Date().toISOString()",
        "source_adapter:",
        "source_adapter_version:",
        "deduplication_key: deduplicationKey",
        "estimated_cost: 0",
        "actual_cost: 0",
    ):
        assert marker in CAPTURE


def test_payload_validation_and_secret_suppression_fail_closed() -> None:
    auth = CAPTURE.index("if (!isAuthenticated(req))")
    parse = CAPTURE.index('body = JSON.parse(raw || "{}")')
    crm = CAPTURE.index("await Promise.all")
    assert auth < parse < crm
    for error in (
        "unauthorized",
        "payload_too_large",
        "invalid_json",
        "communication_event_identity_required",
        "inbound_communication_fields_required",
        "communication_capture_unavailable",
    ):
        assert error in CAPTURE
    assert '"$1=[redacted]"' in CAPTURE
    assert '"Bearer [redacted]"' in CAPTURE
    assert "console.log" not in CAPTURE
    assert "console.error" not in CAPTURE
    assert "parsed.error" not in CAPTURE
