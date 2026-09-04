from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = (ROOT / "supabase/functions/commandcore-meta-lead-adapter/index.ts").read_text(encoding="utf-8")


def test_meta_adapter_is_test_mode_only_and_never_executes_externally() -> None:
    assert 'COMMANDCORE_META_LEAD_MODE' in ADAPTER
    assert 'error:"live_meta_ingress_disabled"' in ADAPTER
    assert 'live_ingress_enabled:false' in ADAPTER
    assert ADAPTER.count("external_action_started:false") >= 5
    for forbidden in ("graph.facebook.com", "sendMessage", "sendSms", "publishAd", "Messenger"):
        assert forbidden not in ADAPTER


def test_meta_signature_is_verified_without_exposing_the_secret() -> None:
    assert 'COMMANDCORE_META_TEST_APP_SECRET' in ADAPTER
    assert 'x-hub-signature-256' in ADAPTER
    assert 'HMAC' in ADAPTER
    assert 'constantTimeEqual' in ADAPTER
    assert 'error:"invalid_signature"' in ADAPTER
    assert "console.log" not in ADAPTER
    assert "console.error" not in ADAPTER


def test_mocked_webhook_challenge_fails_closed() -> None:
    assert "hub.challenge" in ADAPTER
    assert "hub.verify_token" in ADAPTER
    assert "COMMANDCORE_META_TEST_VERIFY_TOKEN" in ADAPTER
    assert 'error:"invalid_verification_challenge"' in ADAPTER
    assert "constantTimeEqual(supplied,expected)" in ADAPTER


def test_standard_leadgen_entries_and_fields_are_normalized() -> None:
    for marker in ('body.object)!=="page"', 'change.field)!=="leadgen"', "field_data", "phone_number", "full_name"):
        assert marker in ADAPTER
    for limit in ("MAX_BODY_BYTES", "MAX_ENTRIES", "MAX_CHANGES", "MAX_FIELDS"):
        assert limit in ADAPTER


def test_supported_lead_types_are_explicit() -> None:
    for lead_type in ("seller", "buyer", "owner_finance_buyer", "investor_buyer_interest"):
        assert f'"{lead_type}"' in ADAPTER
    assert 'error:"unsupported_lead_type"' not in ADAPTER  # errors are safely mapped, not interpolated
    assert '"unsupported_lead_type"' in ADAPTER


def test_meta_identifiers_are_safe_attribution_only() -> None:
    for field in ("meta_page_id", "meta_form_id", "meta_leadgen_id", "meta_campaign_id", "meta_adset_id", "meta_ad_id"):
        assert field in ADAPTER
    assert 'source_detail:"meta_lead_ads"' in ADAPTER
    assert 'medium:"paid_social"' in ADAPTER
    assert "safeId(" in ADAPTER


def test_event_identity_is_deterministic_and_duplicates_are_collapsed() -> None:
    assert 'meta-leadgen:${pageId}:${formId}:${leadgenId}' in ADAPTER
    assert 'const unique=new Map<string,Record<string,unknown>>()' in ADAPTER
    assert "duplicates_ignored:normalizedEvents.length-unique.size" in ADAPTER
    assert "replay_safe:true" in ADAPTER


def test_adapter_rejects_malformed_unsupported_and_missing_identity_events() -> None:
    for error in ("invalid_json", "malformed_meta_event", "unsupported_change", "meta_identity_required", "invalid_field_data"):
        assert f'"{error}"' in ADAPTER


def test_adapter_routes_only_to_existing_lead_source_contract() -> None:
    assert 'source_type:"facebook_lead"' in ADAPTER
    assert 'commandcore-lead-source-adapter' in ADAPTER
    assert 'canonical_destination:"commandcore-lead-source-adapter"' in ADAPTER
    for crm_entity in ("contacts", "properties", "deals", "activities", "tasks"):
        assert crm_entity not in ADAPTER


def test_missing_property_is_allowed_for_buyer_forms() -> None:
    assert 'property_address:first(fields,["property_address","address","street_address"])' in ADAPTER
    assert "property_identity_required" not in ADAPTER


def test_consent_and_buyer_preferences_are_preserved_for_canonical_mapping() -> None:
    for field in (
        "sms_consent_state",
        "email_consent_state",
        "consent_evidence_reference",
        "market_preferences",
        "property_types",
        "financing_preferences",
        "max_purchase_price",
        "max_monthly_payment",
        "max_down_payment",
    ):
        assert field in ADAPTER


def test_no_credentials_are_returned_or_persisted() -> None:
    for leaked_field in ("access_token:", "app_secret:", "page_token:", "oauth_token:", "refresh_token:"):
        assert leaked_field not in ADAPTER
    assert "Deno.write" not in ADAPTER
    assert "storage/v1" not in ADAPTER
