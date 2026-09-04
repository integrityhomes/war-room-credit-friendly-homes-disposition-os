from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = (ROOT / "supabase/functions/commandcore-public-lead-gateway/index.ts").read_text(encoding="utf-8")
ADAPTER = (ROOT / "supabase/functions/commandcore-lead-source-adapter/index.ts").read_text(encoding="utf-8")
CAPTURE = (ROOT / "supabase/functions/commandcore-inbound-lead-capture/index.ts").read_text(encoding="utf-8")


def test_public_gateway_security_controls_remain_in_place() -> None:
    for marker in (
        "configuredOrigins()",
        "rateAllowed(clientIp(req))",
        "body.website||body.company||body.middle_name||body.honeypot",
        "MAX_BODY_BYTES",
        "if(!phone&&!email)",
        "granted_consent_requires_evidence",
    ):
        assert marker in GATEWAY


def test_malformed_and_incomplete_submissions_fail_safely() -> None:
    assert 'error:"invalid_json"' in GATEWAY
    assert 'error:"lead_identity_required"' in GATEWAY
    assert 'error:"unsupported_lead_type"' in GATEWAY
    assert 'error:"lead_gateway_unavailable"' in GATEWAY


def test_adapter_uses_canonical_event_and_retains_legacy_path() -> None:
    assert '"meta.lead_submitted":"website.lead_submitted"' in ADAPTER
    assert '"commandcore-inbound-lead-capture"' in ADAPTER
    assert 'body.compatibility_mode==="legacy_lead_intake"' in ADAPTER
    assert 'sourceType==="website_form"||sourceType==="property_page"' in ADAPTER
    assert '"commandcore-lead-intake"' in ADAPTER
    assert "legacy_intake_available:true" in ADAPTER


def test_all_approved_website_lead_types_are_distinct() -> None:
    for lead_type in (
        "seller",
        "buyer",
        "owner_finance_buyer",
        "investor_buyer_interest",
    ):
        assert f'"{lead_type}"' in GATEWAY
        assert f'"{lead_type}"' in ADAPTER
        assert f'"{lead_type}"' in CAPTURE


def test_seller_lead_requires_property_and_builds_unified_deal_chain() -> None:
    assert 'normalizedLeadType === "seller"' in CAPTURE
    assert 'error: "seller_property_identity_required"' in CAPTURE
    for entity in ("contacts", "properties", "deals", "activities", "tasks"):
        assert f'callCrm(supabaseUrl, serviceKey, "{entity}"' in CAPTURE
    assert "propertyParts.some(Boolean)" in CAPTURE


def test_buyer_leads_preserve_existing_buyer_profile_architecture() -> None:
    assert 'function isBuyerLead(value: string)' in CAPTURE
    assert '"commandcore-buyer-profile"' in CAPTURE
    for field in (
        "market_preferences",
        "property_types",
        "financing_preferences",
        "max_purchase_price",
        "max_monthly_payment",
    ):
        assert field in CAPTURE


def test_consent_evidence_uses_existing_contact_ledger() -> None:
    assert '"commandcore-contact-ledger"' in CAPTURE
    assert "consent_evidence_reference" in ADAPTER
    assert "sms_consent_evidence" in ADAPTER
    assert "email_consent_evidence" in ADAPTER
    assert 'state === "granted" && !evidence' in CAPTURE
    assert 'error: "granted_consent_requires_evidence"' in CAPTURE


def test_contact_property_deal_activity_and_followup_are_deterministic() -> None:
    for marker in (
        "canonical-contact-${contactStable}",
        "canonical-property-${propertyStable}",
        "canonical-deal-${dealStable}",
        "canonical-intake-${dealStable}",
        "canonical-follow-up-${dealStable}",
    ):
        assert marker in CAPTURE
    assert "deterministicCrmId(" in CAPTURE


def test_duplicate_deal_preserves_existing_owner_without_hard_coding() -> None:
    assert "const existingOwner = text(existingDeal?.assigned_to);" in CAPTURE
    assert 'status: "preserved", owner_name: existingOwner' in CAPTURE
    assert "const assignedTo = existingOwner || explicitOwner" in CAPTURE
    assert "existing_owner_preserved: Boolean(existingOwner)" in CAPTURE
    assert 'const explicitOwner = callerAuth === "service_role" ? requestedOwner : "";' in CAPTURE


def test_source_and_campaign_attribution_flow_to_deal_activity_and_task() -> None:
    for field in ("campaign", "medium", "source_detail", "source_event_id"):
        assert field in ADAPTER
        assert field in CAPTURE
    assert CAPTURE.count("source_attribution:") >= 3


def test_followup_uses_existing_task_record_without_outbound_execution() -> None:
    for marker in (
        'task_type: "crm_follow_up"',
        'work_type: "lead_follow_up"',
        'status: text(existingFollowUp?.status) || "open"',
        "assigned_to: assignedTo",
        "external_action_started: false",
        "outbound_communications_triggered: 0",
    ):
        assert marker in CAPTURE
    for forbidden in ("sendSms", "sendEmail", "sendMessage", "makeCall"):
        assert forbidden not in CAPTURE
