from __future__ import annotations

from typing import Any

from .contract_deal_facts import assemble_contract_facts
from .contract_reader import ContractReview, review_contract
from .contract_review_facts import review_facts_from_verified_contract_facts
from .contract_review_records import contract_review_activity, contract_review_document


def build_contract_review_package(
    *,
    deal_id: str,
    deal: dict[str, Any],
    seller: dict[str, Any] | None,
    property_record: dict[str, Any] | None,
    source_document: dict[str, Any],
    file_content: bytes,
    review_version: int,
) -> tuple[ContractReview, dict[str, Any], dict[str, Any]]:
    facts, _missing = assemble_contract_facts(
        deal=deal,
        seller=seller,
        property_record=property_record,
    )
    review = review_contract(
        str(source_document.get("name") or "contract"),
        file_content,
        review_facts_from_verified_contract_facts(facts),
    )
    review_document = contract_review_document(
        deal_id=deal_id,
        source_document_id=str(source_document.get("id") or "").strip(),
        source_document_version=source_document.get("version") or 1,
        source_file_name=str(source_document.get("name") or "Contract").strip(),
        review=review,
    )
    review_document["version"] = review_version
    activity = contract_review_activity(
        source_file_name=str(source_document.get("name") or "Contract").strip(),
        review_document=review_document,
    )
    return review, review_document, activity


def review_status_label(review_document: dict[str, Any]) -> str:
    counts = review_document.get("finding_counts")
    counts = counts if isinstance(counts, dict) else {}
    needs_review = int(counts.get("needs_review") or 0)
    missing = int(counts.get("missing_deal_fact") or 0)
    if needs_review:
        return "Needs attention"
    if missing:
        return "Missing Deal facts"
    return "Looks good"
