# ruff: noqa: I001
from pathlib import Path


def test_contract_review_runs_live_and_stays_deal_native() -> None:
    source = Path("src/cfh_disposition/commandcore_contract_workspace_ui.py").read_text(encoding="utf-8")

    assert 'st.button("Review Now"' in source
    assert "ContractFileStore(get_supabase()).download(object_path)" in source
    assert "review_contract(file_name, file_bytes, reader_facts)" in source
    assert "contract_review_document(" in source
    assert 'save_related("documents", deal_id, review_record)' in source
    assert 'save_related("activities", deal_id, activity)' in source
    assert "Looks good so far" in source
    assert "Needs attention" in source
    assert "Missing Deal fact" in source
    assert "Nothing was signed, sent, or changed" in source
    assert "Contract review request added to this Deal" not in source
