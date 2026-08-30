# ruff: noqa: I001
from pathlib import Path


def test_live_contract_review_reads_canonical_private_storage_path() -> None:
    source = Path("src/cfh_disposition/commandcore_contract_review_ui.py").read_text(encoding="utf-8")

    assert 'source_document.get("storage_object_path")' in source
    assert 'ContractFileStore(client).download(object_path)' in source
    assert 'The stored contract file could not be located for review.' in source
