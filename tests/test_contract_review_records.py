from cfh_disposition.contract_reader import ContractFinding, ContractReview
from cfh_disposition.contract_review_records import contract_review_activity, contract_review_document


def test_review_record_links_exact_source_version_and_stays_non_authoritative() -> None:
    review = ContractReview(
        extracted_text="Seller Jane Smith",
        extraction_status="readable_text_extracted",
        findings=(
            ContractFinding(
                key="seller",
                label="Seller",
                expected_value="Jane Smith",
                status="found",
                detail="The verified Deal value appears in the contract text.",
            ),
            ContractFinding(
                key="property",
                label="Property",
                expected_value="123 Main Street",
                status="needs_review",
                detail="The verified Deal value was not found exactly in the contract text. Review this item before approval.",
            ),
        ),
    )

    record = contract_review_document(
        deal_id="deal-1",
        source_document_id="doc-7",
        source_document_version=3,
        source_file_name="purchase-contract.pdf",
        review=review,
    )

    assert record["status"] == "needs_attention"
    assert record["source_document_id"] == "doc-7"
    assert record["source_document_version"] == 3
    assert record["finding_counts"] == {"found": 1, "needs_review": 1, "missing_deal_fact": 0}
    assert record["legal_conclusion_made"] is False
    assert record["approval_granted"] is False
    assert record["signing_started"] is False
    assert record["external_action_started"] is False

    activity = contract_review_activity(source_file_name="purchase-contract.pdf", review_document=record)
    assert "1 item(s) need attention" in activity["summary"]
    assert activity["details"]["source_document_version"] == 3
