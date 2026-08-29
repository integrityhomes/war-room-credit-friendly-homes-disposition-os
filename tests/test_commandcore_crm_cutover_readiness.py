from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-launch-readiness/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-launch-readiness.yml"


def test_launch_readiness_keeps_operational_and_crm_cutover_signals_separate() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert "const SYSTEM_OF_RECORD_ENTITIES" in source
    assert "crm_cutover: crmCutover" in source
    assert "launch_ready: ready" in source
    assert "crm_cutover_ready: false" in source
    assert "source_crm_data_reconciliation_verified: false" in source
    assert "migration_platform_ready: platformReady" in source


def test_crm_cutover_assessment_requires_all_system_of_record_mappings() -> None:
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
    assert "unsupported_migration_entities: missing" in source
    assert "complete_mapping_coverage: completeMappingCoverage" in source
    assert "migration_mapping_missing:" in source


def test_crm_cutover_assessment_requires_guarded_apply_and_private_backup() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'getServiceHealth(url, key, "commandcore-crm-import-staging")' in source
    assert 'getServiceHealth(url, key, "commandcore-crm-import-commit")' in source
    assert 'getServiceHealth(url, key, "commandcore-crm-backup")' in source
    assert "commit.signed_preview_required_for_apply === true" in source
    assert "commit.pre_apply_backup_required === true" in source
    assert "commit.explicit_update_permission_required === true" in source
    assert "backup.backup_bucket_private_required === true" in source
    assert "backup.destructive_cleanup_enabled === false" in source


def test_launch_readiness_deploy_validates_and_verifies_cutover_guard() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert "deno check supabase/functions/commandcore-launch-readiness/index.ts" in workflow
    assert 'data.get("launch_ready") is True' in workflow
    assert 'cutover.get("crm_cutover_ready") is False' in workflow
    assert 'cutover.get("source_crm_data_reconciliation_verified") is False' in workflow
    assert "SUPABASE_PROJECT_REF" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" in workflow
