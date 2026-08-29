from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-crm-reconciliation/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-crm-reconciliation.yml"


def test_reconciliation_is_read_only_until_explicit_owner_verification() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'action === "preview"' in source
    assert 'reconciliation_verified: false' in source
    assert 'verification_record_written: false' in source
    assert 'body.owner_approved !== true' in source
    assert 'text(body.confirmation_phrase) !== "VERIFY CRM RECONCILIATION"' in source
    assert 'error: "explicit_owner_reconciliation_approval_required"' in source
    assert 'error: "real_source_export_required"' in source
    assert 'error: "source_and_commandcore_do_not_match"' in source


def test_reconciliation_covers_all_system_of_record_entities_and_uses_fingerprints() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    for entity in (
        "contacts",
        "properties",
        "deals",
        "activities",
        "communications",
        "tasks",
        "offers",
        "documents",
        "transactions",
    ):
        assert f'"{entity}"' in source
    assert "external_id_sha256" in source
    assert "hashExternalIds" in source
    assert "count_match" in source
    assert "external_id_hash_match" in source
    assert "mismatched_entities" in source


def test_synthetic_sources_can_never_record_reconciliation_verification() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert "function syntheticSource" in source
    assert 'source.startsWith("deployment-canary")' in source
    assert 'source.startsWith("synthetic")' in source
    assert "synthetic_canaries_can_verify: false" in source
    assert "!source.real_source_export || syntheticSource(source.source_system)" in source


def test_reconciliation_verification_writes_only_private_aggregate_record() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'const RECONCILIATION_BUCKET = "commandcore-crm-reconciliation"' in source
    assert 'public: false' in source
    assert "source_manifest_contains_raw_records: false" in source
    assert "source_records_modified: false" in source
    assert "commandcore_records_modified: false" in source
    assert "destructive_action_started: false" in source
    assert "external_action_started: false" in source


def test_reconciliation_deploy_canary_is_synthetic_no_write() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "deno check supabase/functions/commandcore-crm-reconciliation/index.ts" in workflow
    assert "synthetic-reconciliation-canary-20260829" in workflow
    assert 'data.get("exact_match") is True' in workflow
    assert 'data.get("eligible_for_owner_verification") is False' in workflow
    assert 'data.get("reconciliation_verified") is False' in workflow
    assert 'data.get("verification_record_written") is False' in workflow
    assert 'data.get("source_records_modified") is False' in workflow
    assert 'data.get("commandcore_records_modified") is False' in workflow
