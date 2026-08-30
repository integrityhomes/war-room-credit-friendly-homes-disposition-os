def read_commit_service() -> str:
    with open("supabase/functions/commandcore-crm-import-commit/index.ts", encoding="utf-8") as handle:
        return handle.read()


def test_apply_requires_explicit_confirmation_and_fresh_signed_preview() -> None:
    source = read_commit_service()

    assert 'error: "confirm_apply_required"' in source
    assert "verifyPreviewToken" in source
    assert 'error: "valid_fresh_preview_token_required"' in source
    assert 'error: "preview_state_changed_repreview_required"' in source


def test_updates_require_separate_permission() -> None:
    source = read_commit_service()

    assert "currentUpdate > 0 && body.allow_updates !== true" in source
    assert 'error: "allow_updates_required"' in source


def test_backup_is_required_before_first_upsert() -> None:
    source = read_commit_service()

    backup_index = source.index('"commandcore-crm-backup"')
    upsert_index = source.index('action: "upsert"')
    assert backup_index < upsert_index
    assert "pre_apply_backup_snapshot_id" in source
    assert 'error instanceof Error ? error.message : "pre_apply_backup_failed"' in source


def test_cutover_commit_never_enables_destructive_delete_or_external_execution() -> None:
    source = read_commit_service()

    assert "destructive_delete_enabled: false" in source
    assert "external_execution_enabled: false" in source
    assert "destructive_delete_used: false" in source
    assert "external_action_started: false" in source
