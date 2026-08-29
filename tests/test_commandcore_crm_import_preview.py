from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT_FUNCTION = ROOT / "supabase/functions/commandcore-crm-import-commit/index.ts"
STAGING_WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-crm-import-staging.yml"
COMMIT_WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-crm-import-commit.yml"


def test_import_commit_dry_run_uses_live_migration_preview_without_writes() -> None:
    source = COMMIT_FUNCTION.read_text(encoding="utf-8")
    assert "const PREVIEW_CHUNK_SIZE = 250" in source
    assert "live_migration_preview_enabled: true" in source
    assert 'action: "migration_preview"' in source
    assert "previewApprovedRows(" in source
    assert "records_written: 0" in source
    assert "source_records_modified: false" in source

    dry_run = source.split("if (!apply) {", 1)[1].split("if (body.confirm_apply !== true)", 1)[0]
    assert "previewApprovedRows(" in dry_run
    assert 'action: "upsert"' not in dry_run
    assert "committed.push" not in dry_run
    assert "records_written: 0" in dry_run
    assert "source_records_modified: false" in dry_run
    assert "preview_token" in dry_run
    assert "apply_guard_ready" in dry_run


def test_import_apply_requires_signed_fresh_preview_and_explicit_confirmation() -> None:
    source = COMMIT_FUNCTION.read_text(encoding="utf-8")
    assert "const PREVIEW_TOKEN_TTL_MS = 30 * 60 * 1000" in source
    assert "signed_preview_required_for_apply: true" in source
    assert "pre_apply_backup_required: true" in source
    assert "explicit_update_permission_required: true" in source
    assert "if (body.confirm_apply !== true)" in source
    assert 'error: "confirm_apply_required"' in source
    assert "verifyPreviewToken(" in source
    assert 'error: "valid_fresh_preview_token_required"' in source
    assert 'error: "preview_state_changed_repreview_required"' in source
    assert 'error: "allow_updates_required"' in source


def test_import_apply_backups_before_first_upsert() -> None:
    source = COMMIT_FUNCTION.read_text(encoding="utf-8")
    backup_position = source.index('callService(supabaseUrl, serviceKey, "commandcore-crm-backup", {})')
    ordered_position = source.index("const ordered = [...approved]")
    upsert_position = source.index('action: "upsert"')
    assert backup_position < ordered_position < upsert_position
    pre_write_guard = source[source.index("if (body.confirm_apply !== true)") : ordered_position]
    assert 'action: "upsert"' not in pre_write_guard
    assert "records_written: 0" in pre_write_guard
    assert "source_records_modified: false" in pre_write_guard


def test_import_commit_real_apply_path_remains_explicit_and_separate() -> None:
    source = COMMIT_FUNCTION.read_text(encoding="utf-8")
    apply_path = source.split("const ordered =", 1)[1]
    assert 'action: "upsert"' in apply_path
    assert "committed.push" in apply_path
    assert "apply_requested: true" in apply_path
    assert "apply_guard_verified: true" in apply_path
    assert "pre_apply_backup_snapshot_id" in apply_path
    assert "destructive_delete_used: false" in apply_path
    assert "external_action_started: false" in apply_path


def test_importer_deploy_workflows_use_project_ref_and_non_writing_canaries() -> None:
    staging = STAGING_WORKFLOW.read_text(encoding="utf-8")
    commit = COMMIT_WORKFLOW.read_text(encoding="utf-8")

    for workflow in (staging, commit):
        assert "branches: [main]" in workflow
        assert "SUPABASE_PROJECT_REF" in workflow
        assert "SUPABASE_SERVICE_ROLE_KEY" in workflow
        assert "secrets.SUPABASE_URL" not in workflow
        assert "deno check supabase/functions/commandcore-crm-import-" in workflow

    assert 'data.get("commit_performed") is False' in staging
    assert '"apply":false' in commit
    assert 'data.get("records_written") == 0' in commit
    assert 'data.get("source_records_modified") is False' in commit
    assert 'data.get("live_preview_ok") is True' in commit
