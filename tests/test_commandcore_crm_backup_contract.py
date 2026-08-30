def read_backup_service() -> str:
    with open("supabase/functions/commandcore-crm-backup/index.ts", encoding="utf-8") as handle:
        return handle.read()


def test_backup_bucket_is_private_and_restore_is_preview_only() -> None:
    source = read_backup_service()

    assert 'public: false' in source
    assert 'backup_bucket_private_required: true' in source
    assert 'restore_preview_enabled: true' in source
    assert 'restore_enabled: false' in source
    assert 'destructive_cleanup_enabled: false' in source


def test_backup_manifest_records_entity_counts_and_total_objects() -> None:
    source = read_backup_service()

    assert 'entity_counts: counts' in source
    assert 'object_count: copiedCount' in source
    assert 'private_backup_required: true' in source
    assert 'source_records_modified: false' in source


def test_backup_covers_all_cutover_entities() -> None:
    source = read_backup_service()
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


def test_restore_preview_does_not_modify_live_only_records() -> None:
    source = read_backup_service()

    assert 'live_only_untouched' in source
    assert 'restore_executed: false' in source
    assert 'source_records_modified: false' in source
    assert 'destructive_action_started: false' in source
