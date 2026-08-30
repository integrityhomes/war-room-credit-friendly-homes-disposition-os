from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from cfh_disposition.contract_review_pipeline import (
    build_contract_review_package,
    review_status_label,
)


def _docx_bytes(text: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    return buffer.getvalue()


def test_review_package_uses_verified_deal_facts_and_links_source_version() -> None:
    review, record, activity = build_contract_review_package(
        deal_id="deal-1",
        deal={
            "contract_type": "Illinois CFD",
            "purchase_price": "45000",
            "buyer_1_name": "John Buyer",
        },
        seller={"name": "Jane Seller"},
        property_record={
            "state": "Illinois",
            "address": "123 Main St",
            "legal_description": "Lot 7",
            "parcel_number": "12-34-567-890",
        },
        source_document={"id": "doc-7", "name": "contract.docx", "version": 3},
        file_content=_docx_bytes(
            "Jane Seller 123 Main St 45000 John Buyer Lot 7 12-34-567-890"
        ),
        review_version=2,
    )

    assert record["source_document_id"] == "doc-7"
    assert record["source_document_version"] == 3
    assert record["version"] == 2
    assert record["legal_conclusion_made"] is False
    assert record["external_action_started"] is False
    assert review_status_label(record) == "Missing Deal facts"
    assert activity["activity_type"] == "contract_review_completed"
    assert review.extraction_status == "readable_text_extracted"


def test_review_status_prioritizes_attention_over_missing_facts() -> None:
    assert (
        review_status_label(
            {
                "finding_counts": {
                    "found": 3,
                    "needs_review": 1,
                    "missing_deal_fact": 2,
                }
            }
        )
        == "Needs attention"
    )
    assert review_status_label({"finding_counts": {"found": 5}}) == "Looks good"
