from pathlib import Path

AUTOPILOT = Path("pages/13_AI_Buyer_Reactivation_Autopilot.py")
OLD_PAGE = Path("pages/12_AI_Buyer_Intent_Reactivation.py")


def test_reactivation_is_consolidated_into_one_canonical_page() -> None:
    source = AUTOPILOT.read_text(encoding="utf-8")

    assert not OLD_PAGE.exists()
    assert "Record Engagement" in source
    assert "record_signal" in source
    assert "Automation History" in source
    assert "Build AI Reactivation Sequences" in source


def test_reactivation_blocks_non_marketable_properties_and_locks_approved_content() -> None:
    source = AUTOPILOT.read_text(encoding="utf-8")

    assert "MARKETABLE_PROPERTY_STATUSES" in source
    assert "property_record.status not in MARKETABLE_PROPERTY_STATUSES" in source
    assert "No Ready to Launch or Marketing Live property is available" in source
    assert 'key=f"message_{selected.job_id}", disabled=True' in source
    assert 'key=f"link_{selected.job_id}", disabled=True' in source
