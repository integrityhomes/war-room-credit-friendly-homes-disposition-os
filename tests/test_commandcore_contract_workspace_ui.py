# ruff: noqa: I001
from cfh_disposition.commandcore_contract_workspace_ui import _next_version, _review_task_exists
from cfh_disposition.contract_workspace import DocumentPurpose


def test_next_upload_version_advances_only_matching_contract_type() -> None:
    documents = [
        {"document_type": "uploaded_contract", "version": 1},
        {"document_type": "uploaded_contract", "version": 3},
        {"document_type": "generated_contract", "version": 8},
    ]

    assert _next_version(documents, DocumentPurpose.UPLOADED_CONTRACT) == 4
    assert _next_version(documents, DocumentPurpose.GENERATED_CONTRACT) == 9


def test_review_request_is_deduplicated_by_document() -> None:
    tasks = [
        {
            "work_type": "review_contract",
            "status": "open",
            "links": {"document_id": "doc-1"},
        },
        {
            "work_type": "review_contract",
            "status": "completed",
            "links": {"document_id": "doc-2"},
        },
    ]

    assert _review_task_exists(tasks, "doc-1") is True
    assert _review_task_exists(tasks, "doc-2") is False
    assert _review_task_exists(tasks, "doc-3") is False
