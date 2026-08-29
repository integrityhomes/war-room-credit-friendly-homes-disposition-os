from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = ROOT / "supabase/functions/commandcore-crm-backup/index.ts"
WORKFLOW = ROOT / ".github/workflows/commandcore-crm-backup.yml"


def test_crm_backup_is_private_and_non_destructive() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'const SOURCE_BUCKET = "commandcore-crm-core"' in source
    assert 'const BACKUP_BUCKET = "commandcore-crm-backups"' in source
    assert "public: false" in source
    assert 'method: "DELETE"' not in source
    assert "source_records_modified: false" in source
    assert "destructive_cleanup_enabled: false" in source
    assert "external_action_started: false" in source


def test_crm_backup_covers_all_system_of_record_entities() -> None:
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


def test_crm_backup_deploys_from_main_and_runs_nightly() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main]" in workflow
    assert 'cron: "10 6 * * *"' in workflow
    assert "supabase functions deploy commandcore-crm-backup" in workflow
    assert "SUPABASE_PROJECT_REF" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" in workflow
    assert "source_records_modified" in workflow
    assert "destructive_action_started" in workflow
    assert "external_action_started" in workflow
    assert "upload-artifact" not in workflow


def test_restore_capability_is_preview_only() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert 'action === "list_snapshots"' in source
    assert 'action === "preview_restore"' in source
    assert "restore_preview_enabled: true" in source
    assert "restore_enabled: false" in source
    assert "restore_executed: false" in source
    assert 'action === "restore"' not in source
    assert 'action === "apply_restore"' not in source
    assert 'method: "PUT"' not in source
    assert 'method: "PATCH"' not in source


def test_restore_preview_reports_counts_not_record_contents() -> None:
    source = FUNCTION.read_text(encoding="utf-8")
    assert "would_create" in source
    assert "would_overwrite" in source
    assert "unchanged" in source
    assert "live_only_untouched" in source
    assert "manifest_valid" in source
    assert 'crypto.subtle.digest(' in source
    assert "backupRaw" not in source.split("return {", 1)[0] or "snapshot_objects" in source
