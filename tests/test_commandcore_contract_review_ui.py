from cfh_disposition.commandcore_contract_review_ui import (
    _latest_review,
    _next_review_version,
)


def test_review_versions_are_scoped_to_source_document() -> None:
    documents = [
        {
            "document_type": "contract_review",
            "source_document_id": "doc-1",
            "version": 1,
        },
        {
            "document_type": "contract_review",
            "source_document_id": "doc-1",
            "version": 2,
        },
        {
            "document_type": "contract_review",
            "source_document_id": "doc-2",
            "version": 7,
        },
    ]

    assert _next_review_version(documents, "doc-1") == 3
    assert _next_review_version(documents, "doc-2") == 8
    assert _next_review_version(documents, "doc-3") == 1


def test_latest_review_returns_latest_for_exact_contract_version() -> None:
    documents = [
        {
            "id": "review-1",
            "document_type": "contract_review",
            "source_document_id": "doc-1",
            "version": 1,
        },
        {
            "id": "review-2",
            "document_type": "contract_review",
            "source_document_id": "doc-1",
            "version": 2,
        },
    ]

    latest = _latest_review(documents, "doc-1")
    assert latest is not None
    assert latest["id"] == "review-2"
    assert _latest_review(documents, "missing") is None
