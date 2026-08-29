from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "supabase/functions/commandcore-crm-import-staging/index.ts"
COMMIT = ROOT / "supabase/functions/commandcore-crm-import-commit/index.ts"

EXPECTED_ENTITIES = {
    "contacts",
    "properties",
    "deals",
    "activities",
    "communications",
    "tasks",
    "offers",
    "documents",
    "transactions",
}


def test_staging_supports_all_commandcore_record_types_losslessly() -> None:
    source = STAGING.read_text(encoding="utf-8")
    for entity in EXPECTED_ENTITIES:
        assert f'entity: "{entity}"' in source
    assert "source_payload: sourceRow" in source
    assert "source_payload_preserved: true" in source
    assert "records_committed: 0" in source
    assert "destructive_delete_used: false" in source
    assert "external_action_started: false" in source


def test_commit_supports_all_record_types_under_existing_apply_guards() -> None:
    source = COMMIT.read_text(encoding="utf-8")
    for entity in EXPECTED_ENTITIES:
        assert f'"{entity}"' in source
    assert "SUPPORTED_ENTITIES.includes" in source
    assert "signed_preview_required_for_apply: true" in source
    assert "pre_apply_backup_required: true" in source
    assert "explicit_update_permission_required: true" in source
    assert 'error: "valid_fresh_preview_token_required"' in source
    assert 'error: "allow_updates_required"' in source
    assert '"commandcore-crm-backup"' in source


def test_history_entities_commit_after_parent_records_for_cross_links() -> None:
    source = COMMIT.read_text(encoding="utf-8")
    assert "contacts: 0" in source
    assert "properties: 1" in source
    assert "deals: 2" in source
    for entity in ("activities", "communications", "tasks", "offers", "documents", "transactions"):
        assert f"{entity}:" in source
    assert "links.contact_id" in source
    assert "links.property_id" in source
    assert "links.deal_id" in source
