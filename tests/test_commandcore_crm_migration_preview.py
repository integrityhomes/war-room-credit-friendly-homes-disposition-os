from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-crm-core/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-crm-core.yml"


def test_migration_preview_is_bounded_and_bulk_apply_stays_disabled() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert "const MAX_MIGRATION_PREVIEW = 250" in source
    assert 'migration_preview_enabled: true' in source
    assert 'migration_bulk_apply_enabled: false' in source
    assert 'error: "external_id_required"' in source
    assert 'error: "duplicate_record_in_batch"' in source
    assert 'records_written: 0' in source
    assert 'source_records_modified: false' in source


def test_migration_preview_block_does_not_write_records() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    preview = source.split('if (action === "migration_preview") {', 1)[1].split(
        'if (action === "get") {', 1
    )[0]
    assert "readRecord(" in preview
    assert "writeRecord(" not in preview
    assert 'migration_bulk_apply_enabled: false' in preview
    assert 'records_written: 0' in preview


def test_crm_core_deploy_runs_deno_and_read_only_production_canary() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main]" in workflow
    assert "deno check supabase/functions/commandcore-crm-core/index.ts" in workflow
    assert "SUPABASE_PROJECT_REF" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" in workflow
    assert '"action":"migration_preview"' in workflow
    assert '"external_id":"commandcore-migration-preview-canary"' in workflow
    assert 'data.get("records_written") == 0' in workflow
    assert 'data.get("source_records_modified") is False' in workflow
    assert 'data.get("migration_bulk_apply_enabled") is False' in workflow
    assert "secrets.SUPABASE_URL" not in workflow
