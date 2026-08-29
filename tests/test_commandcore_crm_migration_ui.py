from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages/43_CommandCore_CRM_Migration.py"


def test_crm_migration_page_hides_signed_preview_token() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "def safe_preview_for_display" in source
    assert 'safe.pop("preview_token", None)' in source
    assert "st.json(safe_preview_for_display(preview))" in source
    assert "st.json(preview)" not in source


def test_crm_migration_page_requires_fresh_guarded_preview_before_apply() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "def preview_is_apply_ready" in source
    assert 'preview.get("apply_guard_ready") is True' in source
    assert 'len(text(preview.get("preview_token"))) > 40' in source
    assert '"apply": False' in source
    assert '"apply": True' in source
    assert '"confirm_apply": True' in source
    assert '"preview_token": preview.get("preview_token")' in source
    assert '"allow_updates": allow_updates' in source


def test_crm_migration_page_invalidates_preview_when_rows_change() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "def payload_signature" in source
    assert "hashlib.sha256" in source
    assert "current_payload_signature = payload_signature(payload_rows)" in source
    assert 'st.session_state.crm_migration_preview_signature = current_payload_signature' in source
    assert "stored_preview_signature != current_payload_signature" in source
    assert 'st.session_state.pop("crm_migration_preview", None)' in source
    assert 'st.session_state.pop("crm_migration_preview_signature", None)' in source
    assert "The approved migration rows changed" in source


def test_crm_migration_page_requires_explicit_overwrite_permission() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "would_update > 0" in source
    assert "I explicitly approve updating" in source
    assert "commit_disabled = not apply_ready or not confirm or (would_update > 0 and not allow_updates)" in source


def test_crm_migration_page_surfaces_backup_and_no_write_safety() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert "create a private backup before the first write" in source
    assert "Staged {result.get('staged_rows', 0)} rows. No CRM records were written." in source
    assert "Preview checks the approved rows against the live CommandCore CRM and writes nothing." in source
    assert "pre_apply_backup_snapshot_id" in source
