from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages/43_CommandCore_CRM_Migration.py"


def test_migration_page_exposes_all_nine_source_export_types() -> None:
    source = PAGE.read_text(encoding="utf-8")
    for entity in (
        "Contacts",
        "Properties",
        "Deals",
        "Activities",
        "Communications",
        "Tasks",
        "Offers",
        "Documents",
        "Transactions",
    ):
        assert f'"{entity}"' in source
    assert 'entity = st.selectbox("Export type", ["Auto detect", *ENTITY_OPTIONS], index=0)' in source


def test_migration_page_builds_reconciliation_manifest_without_displaying_ids() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "def capture_source_export_batch" in source
    assert "def accumulated_source_ids" in source
    assert "def build_source_manifest" in source
    assert "external_id_sha256" in source
    assert "external_id_hash(ids)" in source
    assert "A category is never assumed to be zero" in source
    assert "I verified the source CRM has zero" in source
    assert "st.json(source_manifest)" not in source


def test_reconciliation_preview_is_separate_from_import_apply() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert 'RECONCILIATION_SERVICE = "commandcore-crm-reconciliation"' in source
    assert '{"action": "preview", "source_manifest": source_manifest}' in source
    assert '"action": "record_verified"' in source
    assert '"owner_approved": True' in source
    assert 'confirmation_phrase != "VERIFY CRM RECONCILIATION"' in source
    assert "eligible_for_owner_verification" in source
    assert "This does not migrate, delete, or change CRM records" in source


def test_reconciliation_verification_requires_explicit_owner_action() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "I approve recording this exact real-source reconciliation as verified." in source
    assert 'Type "VERIFY CRM RECONCILIATION" to confirm.' in source
    assert 'st.button("Record Verified Reconciliation"' in source
    assert "verify_disabled" in source
