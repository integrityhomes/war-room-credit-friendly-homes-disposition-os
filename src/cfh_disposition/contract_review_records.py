from __future__ import annotations

from typing import Any

from .contract_reader import ContractReview


def contract_review_document(
    *,
    deal_id: str,
    source_document_id: str,
    source_document_version: int | str,
    source_file_name: str,
    review: ContractReview,
) -> dict[str, Any]:
    findings = [
        {
            "key": finding.key,
            "label": finding.label,
            "expected_value": finding.expected_value,
            "status": finding.status,
            "detail": finding.detail,
        }
        for finding in review.findings
    ]
    needs_review = sum(1 for finding in review.findings if finding.status == "needs_review")
    missing_facts = sum(1 for finding in review.findings if finding.status == "missing_deal_fact")
    found = sum(1 for finding in review.findings if finding.status == "found")

    return {
        "name": f"Contract Review · {source_file_name}",
        "document_type": "contract_review",
        "status": "needs_attention" if needs_review or missing_facts else "review_complete",
        "source": "commandcore-contract-reader",
        "source_document_id": source_document_id,
        "source_document_version": source_document_version,
        "source_file_name": source_file_name,
        "extraction_status": review.extraction_status,
        "finding_counts": {
            "found": found,
            "needs_review": needs_review,
            "missing_deal_fact": missing_facts,
        },
        "findings": findings,
        "legal_conclusion_made": False,
        "legal_terms_changed": False,
        "approval_granted": False,
        "signing_started": False,
        "external_action_started": False,
        "links": {
            "deal_id": deal_id,
            "document_id": source_document_id,
        },
    }


def contract_review_activity(
    *,
    source_file_name: str,
    review_document: dict[str, Any],
) -> dict[str, Any]:
    counts = review_document.get("finding_counts")
    counts = counts if isinstance(counts, dict) else {}
    needs_attention = int(counts.get("needs_review") or 0) + int(counts.get("missing_deal_fact") or 0)
    if needs_attention:
        summary = f"Contract review completed for {source_file_name}: {needs_attention} item(s) need attention."
    else:
        summary = f"Contract review completed for {source_file_name}: verified Deal facts were found."

    return {
        "activity_type": "contract_review_completed",
        "summary": summary,
        "source": "commandcore-contract-reader",
        "details": {
            "source_document_id": review_document.get("source_document_id"),
            "source_document_version": review_document.get("source_document_version"),
            "finding_counts": counts,
            "legal_conclusion_made": False,
            "external_action_started": False,
        },
    }
