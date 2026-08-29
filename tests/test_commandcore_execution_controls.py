from cfh_disposition.commandcore_execution_controls import verified_executed_contract


def test_verified_executed_contract_requires_all_evidence() -> None:
    record = {
        "status": "executed",
        "document_type": "executed_contract",
        "execution_verified": True,
        "signed_document_attached": True,
        "executed_at": "2026-08-29T15:00:00Z",
    }
    assert verified_executed_contract(record) is True


def test_owner_approved_package_is_not_execution() -> None:
    record = {
        "status": "owner_approved",
        "document_type": "contract_assembly_review_package",
        "execution_verified": False,
        "signed_document_attached": False,
    }
    assert verified_executed_contract(record) is False


def test_missing_signed_document_blocks_handoff() -> None:
    record = {
        "status": "executed",
        "document_type": "executed_contract",
        "execution_verified": True,
        "signed_document_attached": False,
        "executed_at": "2026-08-29T15:00:00Z",
    }
    assert verified_executed_contract(record) is False
