# ruff: noqa: I001
import pytest

from cfh_disposition.contract_template_library import (
    next_template_version,
    template_object_path,
    template_record,
)
from cfh_disposition.contract_workspace import ContractWorkspaceError, StoredContractFile


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_template_object_path_is_not_deal_scoped_and_is_immutable_by_version() -> None:
    path = template_object_path(
        contract_type="Illinois Contract for Deed",
        state="IL",
        version=4,
        file_name="Illinois CFD.docx",
    )

    assert path.startswith("templates/il/illinois-contract-for-deed/v4/")
    assert path.endswith(".docx")
    assert not path.startswith("deals/")


def test_template_version_advances_by_contract_type_and_state() -> None:
    documents = [
        {"document_type": "contract_template", "contract_type": "Illinois CFD", "state": "IL", "version": 1},
        {"document_type": "approved_legal_template", "contract_type": "Illinois CFD", "state": "IL", "version": 3},
        {"document_type": "contract_template", "contract_type": "Illinois CFD", "state": "MO", "version": 8},
    ]

    assert next_template_version(documents, contract_type="Illinois CFD", state="IL") == 4
    assert next_template_version(documents, contract_type="Illinois CFD", state="MO") == 9


def test_new_template_version_is_pending_and_cannot_be_used_automatically() -> None:
    record = template_record(
        contract_type="Illinois Contract for Deed",
        state="IL",
        version=2,
        stored=StoredContractFile(
            object_path="templates/il/illinois-contract-for-deed/v2/file.docx",
            file_name="file.docx",
            content_type=DOCX_TYPE,
            size_bytes=123,
        ),
        prior_template_id="template-1",
        change_note="Updated insurance wording for review",
    )

    assert record["status"] == "needs_legal_approval"
    assert record["legal_review_status"] == "pending"
    assert record["legal_approved"] is False
    assert record["approved_for_use"] is False
    assert record["owner_approved"] is False
    assert record["immutable_version"] is True
    assert record["prior_template_id"] == "template-1"
    assert record["legal_terms_changed_by_commandcore"] is False
    assert record["signing_started"] is False
    assert record["external_action_started"] is False


def test_template_requires_package_state_and_positive_version() -> None:
    stored = StoredContractFile(
        object_path="x",
        file_name="file.docx",
        content_type=DOCX_TYPE,
        size_bytes=10,
    )
    with pytest.raises(ContractWorkspaceError):
        template_record(contract_type="", state="IL", version=1, stored=stored)
    with pytest.raises(ContractWorkspaceError):
        template_record(contract_type="Illinois CFD", state="", version=1, stored=stored)
    with pytest.raises(ContractWorkspaceError):
        template_record(contract_type="Illinois CFD", state="IL", version=0, stored=stored)
