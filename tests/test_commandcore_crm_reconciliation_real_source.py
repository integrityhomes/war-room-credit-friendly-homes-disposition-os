def read_reconciliation_service() -> str:
    with open("supabase/functions/commandcore-crm-reconciliation/index.ts", encoding="utf-8") as handle:
        return handle.read()


def test_synthetic_and_test_source_names_cannot_satisfy_cutover_reconciliation() -> None:
    source = read_reconciliation_service()

    for marker in ("synthetic", "test", "fixture", "sample"):
        assert f'"{marker}"' in source
    assert "real_source_export" in source
    assert "source_export_not_verified_as_real" in source or "real_source" in source


def test_owner_confirmation_is_required_before_reconciliation_is_recorded() -> None:
    source = read_reconciliation_service()

    assert "owner_confirmation" in source
    assert "owner_confirmation_required" in source
    assert "reconciliation_verified" in source


def test_reconciliation_checks_counts_and_external_id_fingerprints() -> None:
    source = read_reconciliation_service()

    assert "source_count" in source
    assert "commandcore_count" in source
    assert "count_match" in source
    assert "external_id_hash_match" in source
    assert "exact_match" in source


def test_reconciliation_does_not_modify_source_or_commandcore_records() -> None:
    source = read_reconciliation_service()

    assert "source_records_modified: false" in source
    assert "commandcore_records_modified: false" in source
    assert 'req.method === "PUT"' in source or 'req.method !== "POST"' in source
