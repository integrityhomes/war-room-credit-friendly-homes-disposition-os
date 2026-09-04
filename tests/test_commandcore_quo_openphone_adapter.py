from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = (ROOT / "supabase/functions/commandcore-quo-openphone-adapter/index.ts").read_text(encoding="utf-8")


def test_adapter_is_test_mode_only_and_cannot_contact_external_services() -> None:
    assert "COMMANDCORE_QUO_OPENPHONE_MODE" in ADAPTER
    assert 'error: "live_phone_ingress_disabled"' in ADAPTER
    assert "live_ingress_enabled: false" in ADAPTER
    assert "forwarding_started: false" in ADAPTER
    assert ADAPTER.count("external_action_started: false") >= 8
    assert "fetch(" not in ADAPTER
    for forbidden in ("api.openphone.com", "api.quo.com", "sendMessage", "sendSms", "makeCall", "Deno.connect"):
        assert forbidden not in ADAPTER


def test_signature_validation_is_local_fail_closed_and_secret_safe() -> None:
    assert "COMMANDCORE_QUO_OPENPHONE_TEST_WEBHOOK_SECRET" in ADAPTER
    assert 'req.headers.get("x-openphone-signature")' in ADAPTER
    assert 'req.headers.get("x-quo-signature")' in ADAPTER
    assert 'name: "HMAC", hash: "SHA-256"' in ADAPTER
    assert "constantTimeEqual" in ADAPTER
    assert 'error: "invalid_signature"' in ADAPTER
    assert "console.log" not in ADAPTER
    assert "console.error" not in ADAPTER


def test_all_approved_provider_events_have_canonical_types() -> None:
    mappings = {
        '"message.received": "communication.sms.received"',
        '"message.delivered": "communication.sms.delivery_updated"',
        '"call.incoming": "communication.call.incoming"',
        '"call.completed": "communication.call.completed"',
        '"call.missed": "communication.call.missed"',
        '"voicemail.received": "communication.voicemail.received"',
        '"recording.ready": "communication.recording.ready"',
        '"transcript.ready": "communication.transcript.ready"',
        '"summary.ready": "communication.transcript.ready"',
    }
    for mapping in mappings:
        assert mapping in ADAPTER


def test_normalized_contract_supports_matching_without_writing_crm_records() -> None:
    for field in (
        "event_id",
        "event_type",
        "provider_event_id",
        "provider_object_id",
        "occurred_at",
        "contact_match",
        "communication",
        "source_attribution",
        "follow_up",
        "test_mode",
    ):
        assert field in ADAPTER
    assert 'canonical_destination: "commandcore-inbound-communication-capture"' in ADAPTER
    assert "communication_event: canonicalEvents.length === 1 ? canonicalEvents[0] : null" in ADAPTER
    for crm_entity in ("contacts", "properties", "deals", "activities", "tasks"):
        assert f'"{crm_entity}"' not in ADAPTER
    assert "SUPABASE_SERVICE_ROLE_KEY" not in ADAPTER
    assert "supabase.from" not in ADAPTER


def test_phone_matching_uses_the_other_party_and_requires_safe_phone_identity() -> None:
    assert 'const matchPhone = direction === "inbound" ? from : to;' in ADAPTER
    assert 'contact_match: { phone: matchPhone }' in ADAPTER
    assert 'throw new Error("phone_identity_required")' in ADAPTER
    assert "digits.length < 7 || digits.length > 15" in ADAPTER


def test_only_inbound_actionable_events_recommend_follow_up() -> None:
    for event_type in (
        "communication.sms.received",
        "communication.call.missed",
        "communication.voicemail.received",
    ):
        assert f'eventType === "{event_type}"' in ADAPTER
    assert 'recommended: false, reason: "No automatic follow-up is required for this event"' in ADAPTER
    assert "Reply to the inbound message" in ADAPTER
    assert "Return the missed call" in ADAPTER
    assert "Review the voicemail and follow up" in ADAPTER


def test_duplicate_events_are_collapsed_and_replays_are_safe() -> None:
    assert "const unique = new Map<string, JsonObject>()" in ADAPTER
    assert "unique.set(text(event.event_id), event)" in ADAPTER
    assert "duplicates_ignored: normalizedEvents.length - unique.size" in ADAPTER
    assert "replay_safe: true" in ADAPTER
    assert 'event_id: `${provider}:${eventId}`' in ADAPTER


def test_outbound_sms_is_status_only() -> None:
    assert 'eventType === "communication.sms.delivery_updated"' in ADAPTER
    assert 'return "outbound"' in ADAPTER
    assert "delivery_status" in ADAPTER
    assert "message.sent" not in ADAPTER
    assert "communication.sms.send" not in ADAPTER


def test_recordings_and_transcripts_emit_references_not_secret_urls() -> None:
    assert "recording_reference" in ADAPTER
    assert "transcript_reference" in ADAPTER
    for leaked_field in (
        "recording_url",
        "transcript_url",
        "access_token:",
        "refresh_token:",
        "api_key:",
        "carrier_pin:",
        "password:",
        "webhook_secret:",
    ):
        assert leaked_field not in ADAPTER
    assert "Deno.write" not in ADAPTER
    assert "storage/v1" not in ADAPTER
    assert '"$1=[redacted]"' in ADAPTER
    assert '"Bearer [redacted]"' in ADAPTER


def test_payload_limits_and_safe_errors_precede_normalization() -> None:
    for marker in ("MAX_BODY_BYTES", "MAX_EVENTS", "MAX_TEXT_LENGTH", "safeText", "safeId"):
        assert marker in ADAPTER
    signature = ADAPTER.index("if (!(await validSignature(req, raw)))")
    parsing = ADAPTER.index("body = JSON.parse(raw)")
    normalization = ADAPTER.index("requestEvents(body).map(normalizeEvent)")
    assert signature < parsing < normalization
    for error in (
        "invalid_json",
        "unsupported_provider",
        "unsupported_event_type",
        "event_identity_required",
        "phone_identity_required",
        "invalid_event_count",
        "malformed_phone_event",
    ):
        assert error in ADAPTER
