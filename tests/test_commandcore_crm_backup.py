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
