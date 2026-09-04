from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = (ROOT / "supabase/functions/commandcore-meta-lead-adapter/index.ts").read_text(encoding="utf-8")
ADAPTER = (ROOT / "supabase/functions/commandcore-lead-source-adapter/index.ts").read_text(encoding="utf-8")
CAPTURE = (ROOT / "supabase/functions/commandcore-inbound-lead-capture/index.ts").read_text(encoding="utf-8")


def test_meta_uses_the_existing_canonical_domain_writer() -> None:
    assert 'source_type:"facebook_lead"' in META
    assert "commandcore-lead-source-adapter" in META
    assert '"meta.lead_submitted"' in ADAPTER
    assert '"website.lead_submitted", "meta.lead_submitted"' in CAPTURE
    for entity in ("contacts", "properties", "deals", "activities", "tasks"):
        assert entity not in META
        assert f'callCrm(supabaseUrl, serviceKey, "{entity}"' in CAPTURE


def test_website_sources_remain_on_the_same_canonical_event() -> None:
    assert 'sourceType==="facebook_lead"?"meta.lead_submitted":"website.lead_submitted"' in ADAPTER
    assert 'sourceType==="website_form"||sourceType==="property_page"||sourceType==="facebook_lead"' in ADAPTER
    assert 'body.compatibility_mode==="legacy_lead_intake"' in ADAPTER


def test_all_meta_form_lead_types_flow_to_existing_profiles() -> None:
    for lead_type in ("seller", "buyer", "owner_finance_buyer", "investor_buyer_interest"):
        assert f'"{lead_type}"' in META
        assert f'"{lead_type}"' in ADAPTER
        assert f'"{lead_type}"' in CAPTURE
    assert 'normalizedLeadType === "seller"' in CAPTURE
    assert 'error: "seller_property_identity_required"' in CAPTURE
    assert "propertyStable" in CAPTURE
    assert "propertyParts.some(Boolean)" in CAPTURE


def test_deterministic_meta_replay_reuses_canonical_records() -> None:
    assert 'meta-leadgen:${pageId}:${formId}:${leadgenId}' in META
    assert "duplicates_ignored:normalizedEvents.length-unique.size" in META
    assert "replay_safe:true" in META
    for identity in (
        "canonical-contact-${contactStable}",
        "canonical-property-${propertyStable}",
        "canonical-deal-${dealStable}",
        "canonical-intake-${dealStable}",
        "canonical-follow-up-${dealStable}",
    ):
        assert identity in CAPTURE


def test_meta_attribution_reaches_existing_deal_activity_and_task() -> None:
    for field in (
        "meta_page_id",
        "meta_form_id",
        "meta_leadgen_id",
        "meta_campaign_id",
        "meta_adset_id",
        "meta_ad_id",
    ):
        assert field in META
        assert field in ADAPTER
        assert field in CAPTURE
    assert 'source_detail:"meta_lead_ads"' in META
    assert 'medium:"paid_social"' in META
    assert CAPTURE.count("source_attribution:") >= 3


def test_consent_preferences_owner_and_followup_use_existing_logic() -> None:
    assert '"commandcore-contact-ledger"' in CAPTURE
    assert '"commandcore-buyer-profile"' in CAPTURE
    assert "const existingOwner = text(existingDeal?.assigned_to);" in CAPTURE
    assert "const assignedTo = existingOwner || explicitOwner" in CAPTURE
    assert "existing_owner_preserved: Boolean(existingOwner)" in CAPTURE
    assert 'title: canonicalEventType === "meta.lead_submitted" ? "Follow up with Meta lead"' in CAPTURE
    assert 'task_type: "crm_follow_up"' in CAPTURE
    assert 'work_type: "lead_follow_up"' in CAPTURE


def test_meta_boundary_rejects_bad_requests_before_forwarding() -> None:
    signature = META.index("if(!(await validSignature(req,raw)))")
    parsing = META.index("body=JSON.parse(raw)")
    forwarding = META.index("const results=[]")
    assert signature < parsing < forwarding
    for error in (
        "live_meta_ingress_disabled",
        "invalid_signature",
        "invalid_json",
        "malformed_meta_event",
        "unsupported_change",
        "unsupported_lead_type",
        "meta_identity_required",
    ):
        assert error in META


def test_meta_intake_cannot_start_outbound_execution_or_leak_secrets() -> None:
    combined = "\n".join((META, ADAPTER, CAPTURE))
    assert combined.count("external_action_started:false") >= 3
    assert "outbound_communications_triggered: 0" in CAPTURE
    for forbidden in (
        "graph.facebook.com",
        "sendMessenger",
        "sendSms",
        "sendEmail",
        "makeCall",
        "publishAd",
        "access_token:",
        "page_token:",
        "oauth_token:",
    ):
        assert forbidden not in combined
