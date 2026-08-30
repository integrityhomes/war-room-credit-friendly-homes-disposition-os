from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfWriter

from cfh_disposition.contract_reader import (
    ContractFact,
    ContractReaderError,
    compare_contract_facts,
    extract_contract_text,
)


def _docx_bytes(text: str) -> bytes:
    payload = BytesIO()
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return payload.getvalue()


def test_docx_contract_text_is_read() -> None:
    text = extract_contract_text("contract.docx", _docx_bytes("123 Main Street Purchase Price $25,000"))

    assert "123 Main Street" in text
    assert "$25,000" in text


def test_fact_comparison_marks_found_missing_and_needs_review() -> None:
    findings = compare_contract_facts(
        "Seller Jane Smith agrees to sell 123 Main Street.",
        [
            ContractFact("seller", "Seller", "Jane Smith"),
            ContractFact("address", "Property", "999 Oak Street"),
            ContractFact("parcel", "Parcel", ""),
        ],
    )

    assert [finding.status for finding in findings] == ["found", "needs_review", "missing_deal_fact"]


def test_scanned_or_image_only_pdf_is_not_falsely_reviewed() -> None:
    payload = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(payload)

    with pytest.raises(ContractReaderError, match="scanned/image-only"):
        extract_contract_text("scan.pdf", payload.getvalue())


def test_reader_rejects_unsupported_file_types() -> None:
    with pytest.raises(ContractReaderError, match="PDF and DOCX"):
        extract_contract_text("contract.txt", b"contract")
