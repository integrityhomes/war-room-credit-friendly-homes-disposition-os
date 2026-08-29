from cfh_disposition.commandcore_contract_controls import legal_template_blocker, pending_document


def test_missing_legal_template_is_blocker_not_approvable() -> None:
    record = {"status": "needs_approved_legal_template"}

    assert legal_template_blocker(record) is True
    assert pending_document(record) is False


def test_owner_reviewable_document_statuses_are_approvable() -> None:
    for status in ("needs_owner_approval", "owner_approval_required", "internal_review_ready"):
        record = {"status": status}
        assert pending_document(record) is True
        assert legal_template_blocker(record) is False


def test_completed_or_unrelated_documents_are_not_pending() -> None:
    for status in ("owner_approved", "owner_rejected", "completed", "draft", ""):
        record = {"status": status}
        assert pending_document(record) is False
        assert legal_template_blocker(record) is False
