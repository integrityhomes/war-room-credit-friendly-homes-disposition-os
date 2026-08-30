def read_reconciliation_service() -> str:
    with open("supabase/functions/commandcore-crm-reconciliation/index.ts", encoding="utf-8") as handle:
        return handle.read()


def test_synthetic_and_test_source_names_cannot_satisfy_cutover_reconciliation() -> None:
    source = read_reconciliation_service()

    assert 'source.startsWith("deployment-canary")' in source
    assert 'source.startsWith("synthetic")' in source
    assert 'source.startsWith("test-")' in source
    assert 'source === "test"' in source
    assert "real_source_export" in source
    assert 'error: "real_source_export_required"' in source


def test_explicit_owner_approval_is_required_before_reconciliation_is_recorded() -> None:
    source = read_reconciliation_service()

    assert "body.owner_approved !== true" in source
    assert 'text(body.confirmation_phrase) !== "VERIFY CRM RECONCILIATION"' in source
    assert 'error: "explicit_owner_reconciliation_approval_required"' in source
    assert "verification_record_written: true" in source


def test_reconciliation_checks_counts_and_external_id_fingerprints() -> None:
    source = read_reconciliation_service()

    assert "source_count" in source
    assert "commandcore_count" in source
    assert "count_match" in source
    assert "external_id_hash_match" in source
    assert "exact_match" in source


def test_reconciliation_preview_and_verification_do_not_modify_records() -> None:
    source = read_reconciliation_service()

    assert "source_records_modified: false" in source
    assert "commandcore_records_modified: false" in source
    assert 'req.method !== "POST"' in source
    assert "destructive_delete_enabled: false" in source
    assert "external_execution_enabled: false" in source
