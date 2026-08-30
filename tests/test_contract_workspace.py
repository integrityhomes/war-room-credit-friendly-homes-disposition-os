import pytest

from cfh_disposition.contract_workspace import (
    CONTRACT_BUCKET,
    ContractFile,
    ContractWorkspaceError,
    DocumentPurpose,
    StoredContractFile,
    contract_object_path,
    document_record,
    validate_contract_file,
)


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_contract_upload_accepts_pdf_and_docx() -> None:
    validate_contract_file(
        ContractFile("signed.pdf", b"pdf-bytes", "application/pdf"),
        DocumentPurpose.UPLOADED_CONTRACT,
    )
    validate_contract_file(
        ContractFile("draft.docx", b"docx-bytes", DOCX_TYPE),
        DocumentPurpose.UPLOADED_CONTRACT,
    )


def test_template_upload_requires_docx() -> None:
    with pytest.raises(ContractWorkspaceError):
        validate_contract_file(
            ContractFile("template.pdf", b"pdf", "application/pdf"),
            DocumentPurpose.CONTRACT_TEMPLATE,
        )


def test_object_path_is_versioned_and_deal_scoped() -> None:
    path = contract_object_path(
        deal_id="deal-123",
        purpose=DocumentPurpose.UPLOADED_CONTRACT,
        version=2,
        file_name="Seller Contract.pdf",
    )

    assert path.startswith("deals/deal-123/uploaded_contract/v2/")
    assert path.endswith(".pdf")


def test_document_record_preserves_private_provenance_and_safety_flags() -> None:
    record = document_record(
        deal_id="deal-123",
        purpose=DocumentPurpose.GENERATED_CONTRACT,
        stored=StoredContractFile(
            object_path="deals/deal-123/generated_contract/v3/generated.docx",
            file_name="generated.docx",
            content_type=DOCX_TYPE,
            size_bytes=1234,
        ),
        version=3,
        template_family="Illinois CFD",
        template_version="V14",
        prior_document_id="doc-2",
    )

    assert record["storage_bucket"] == CONTRACT_BUCKET
    assert record["storage_object_path"].startswith("deals/deal-123/")
    assert record["immutable_version"] is True
    assert record["template_family"] == "Illinois CFD"
    assert record["template_version"] == "V14"
    assert record["prior_document_id"] == "doc-2"
    assert record["legal_terms_generated"] is False
    assert record["legal_terms_changed"] is False
    assert record["signing_started"] is False
    assert record["external_action_started"] is False
    assert record["links"]["deal_id"] == "deal-123"


def test_template_record_starts_unapproved() -> None:
    record = document_record(
        deal_id="deal-template-library",
        purpose=DocumentPurpose.CONTRACT_TEMPLATE,
        stored=StoredContractFile(
            object_path="deals/deal-template-library/contract_template/v1/template.docx",
            file_name="template.docx",
            content_type=DOCX_TYPE,
            size_bytes=100,
        ),
        version=1,
        template_family="Illinois CFD",
        template_version="V15",
    )

    assert record["status"] == "needs_legal_approval"
    assert record["document_type"] == "contract_template"


def test_template_family_is_required() -> None:
    with pytest.raises(ContractWorkspaceError):
        document_record(
            deal_id="deal-template-library",
            purpose=DocumentPurpose.CONTRACT_TEMPLATE,
            stored=StoredContractFile(
                object_path="x",
                file_name="template.docx",
                content_type=DOCX_TYPE,
                size_bytes=10,
            ),
            version=1,
        )
