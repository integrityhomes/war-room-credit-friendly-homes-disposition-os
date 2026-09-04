from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = (ROOT / "supabase/functions/commandcore-quo-openphone-adapter/index.ts").read_text(encoding="utf-8")


def test_adapter_uses_documented_quo_signature_and_replay_protection() -> None:
    for marker in (
        'req.headers.get("openphone-signature")',
        'supplied.trim().split(";")',
        'scheme !== "hmac"',
        'version !== "1"',
        "SIGNATURE_TOLERANCE_MS",
        "Math.abs(now - timestamp) > SIGNATURE_TOLERANCE_MS",
        "decodeBase64(encodedSecret)",
        "`${timestampText}.${canonicalJson(raw)}`",
        '{ name: "HMAC", hash: "SHA-256" }',
        "constantTimeEqual(providedDigest, digest)",
    ):
        assert marker in ADAPTER
    assert "COMMANDCORE_QUO_OPENPHONE_WEBHOOK_SECRET" in ADAPTER
    assert "COMMANDCORE_QUO_OPENPHONE_TEST_WEBHOOK_SECRET" in ADAPTER


def test_live_ingress_requires_separate_explicit_activation() -> None:
    assert 'lower(Deno.env.get("COMMANDCORE_QUO_OPENPHONE_MODE")) === "inbound"' in ADAPTER
    assert 'status: inboundEnabled() ? "inbound_only" : "activation_required"' in ADAPTER
    assert "live_ingress_enabled: inboundEnabled()" in ADAPTER
    assert 'error: "live_phone_ingress_disabled"' in ADAPTER


def test_inbound_openphone_sms_normalizes_real_payload_shape() -> None:
    for marker in (
        'rawType === "message.received"',
        'return "communication.sms.received"',
        'supplied === "incoming" || supplied === "inbound"',
        "data.object || data",
        "data.text, data.body",
        "data.conversationId, data.conversation_id",
        'contact_match: { phone: from }',
        'channel: eventType.includes(".sms.") ? "sms" : "phone"',
    ):
        assert marker in ADAPTER


def test_known_and_unknown_contacts_both_route_to_existing_capture() -> None:
    assert 'canonical_destination: "commandcore-inbound-communication-capture"' in ADAPTER
    assert "async function captureInbound" in ADAPTER
    assert "JSON.stringify({ communication_event: event })" in ADAPTER
    assert "contact_match: { phone: from }" in ADAPTER
    assert "commandcore-crm-core" not in ADAPTER
    assert '"contacts"' not in ADAPTER


def test_stop_sms_body_reaches_phase_three_capture_without_consent_mutation() -> None:
    assert "summary: eventSummary(eventType, data)" in ADAPTER
    assert "consent_mutations" not in ADAPTER
    assert "commandcore-contact-ledger" not in ADAPTER
    assert "record_consent" not in ADAPTER


def test_missed_inbound_call_is_normalized_without_callback() -> None:
    assert '["call.missed", "call.no_answer"]' in ADAPTER
    assert "!text(data.answeredAt || data.answered_at)" in ADAPTER
    assert 'return "communication.call.missed"' in ADAPTER
    assert 'return "Missed inbound call"' in ADAPTER
    assert 'status: eventType === "communication.call.missed" ? "missed" : "received"' in ADAPTER
    assert "returnCall" not in ADAPTER


def test_voicemail_uses_only_supplied_safe_metadata_and_no_paid_transcription() -> None:
    assert "Object.keys(objectValue(data.voicemail)).length" in ADAPTER
    assert 'return "communication.voicemail.received"' in ADAPTER
    assert 'return "Inbound voicemail received"' in ADAPTER
    assert "voicemail_duration_seconds" in ADAPTER
    assert "voicemail.url" not in ADAPTER
    assert "recording_url" not in ADAPTER
    assert "transcription" not in ADAPTER.casefold()


def test_duplicate_webhooks_and_retries_create_at_most_one_communication() -> None:
    assert "const unique = new Map<string, JsonObject>()" in ADAPTER
    assert "unique.set(text(event.event_id), event)" in ADAPTER
    assert "duplicates_ignored_in_request: normalizedEvents.length - unique.size" in ADAPTER
    assert "duplicate_retries_ignored:" in ADAPTER
    assert "item.duplicate_ignored === true" in ADAPTER
    assert "item.communication_created === true" in ADAPTER


def test_outbound_and_unknown_direction_events_fail_closed() -> None:
    assert 'supplied === "outgoing" || supplied === "outbound"' in ADAPTER
    assert 'throw new Error("outbound_event_rejected")' in ADAPTER
    assert 'throw new Error("communication_direction_required")' in ADAPTER
    assert '"outbound_event_rejected"' in ADAPTER
    assert "outbound_enabled: false" in ADAPTER


def test_malformed_events_fail_closed_with_allowlisted_errors() -> None:
    signature = ADAPTER.index("if (!(await validSignature(req, raw)))")
    parsing = ADAPTER.index("body = JSON.parse(raw)")
    normalization = ADAPTER.index("requestEvents(body).map(normalizeEvent)")
    capture = ADAPTER.index("captureResults.push(await captureInbound(event))")
    assert signature < parsing < normalization < capture
    for error in (
        "invalid_signature",
        "invalid_json",
        "unsupported_event_type",
        "event_identity_required",
        "phone_identity_required",
        "outbound_event_rejected",
        "inbound_capture_unavailable",
    ):
        assert error in ADAPTER


def test_secret_values_and_provider_response_bodies_are_never_logged() -> None:
    assert '"$1=[redacted]"' in ADAPTER
    assert '"Bearer [redacted]"' in ADAPTER
    for forbidden in (
        "console.log",
        "console.error",
        "api.openphone.com",
        "api.quo.com",
        "access_token:",
        "private_key:",
        "webhook_secret:",
        "result.error",
    ):
        assert forbidden not in ADAPTER


def test_absolute_outbound_and_business_record_mutation_block() -> None:
    for marker in (
        "outbound_messages: 0",
        "outbound_calls: 0",
        "contact_mutations: 0",
        "deal_mutations: 0",
        "property_mutations: 0",
        "external_action_started: false",
    ):
        assert marker in ADAPTER
    for forbidden in (
        "sendMessage",
        "sendSms",
        "sendEmail",
        "makeCall",
        "createContact",
        "updateContact",
        "updateDeal",
        "updateProperty",
    ):
        assert forbidden not in ADAPTER


def test_source_identity_and_zero_cost_metadata_are_preserved() -> None:
    for marker in (
        'event_id: `${provider}:${eventId}`',
        "provider_event_id: eventId",
        "provider_object_id: objectId",
        "source_conversation_id: sourceConversationId || null",
        'source_adapter: "commandcore-quo-openphone-adapter"',
        "source_adapter_version: SERVICE_VERSION",
        "estimated_cost: 0",
        "actual_cost: 0",
    ):
        assert marker in ADAPTER
