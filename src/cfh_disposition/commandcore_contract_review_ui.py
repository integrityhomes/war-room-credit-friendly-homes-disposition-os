from __future__ import annotations

from typing import Any

import streamlit as st

from .contract_reader import ContractReaderError
from .contract_review_pipeline import build_contract_review_package, review_status_label
from .contract_workspace import ContractFileStore, ContractWorkspaceError


def _text(value: Any) -> str:
    return str(value or "").strip()


def _links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def _next_review_version(documents: list[dict[str, Any]], source_document_id: str) -> int:
    versions: list[int] = []
    for document in documents:
        if _text(document.get("document_type")) != "contract_review":
            continue
        if _text(document.get("source_document_id")) != source_document_id:
            continue
        try:
            versions.append(int(document.get("version") or 0))
        except (TypeError, ValueError):
            continue
    return max(versions, default=0) + 1


def _latest_review(documents: list[dict[str, Any]], source_document_id: str) -> dict[str, Any] | None:
    reviews = [
        document
        for document in documents
        if _text(document.get("document_type")) == "contract_review"
        and _text(document.get("source_document_id")) == source_document_id
    ]
    if not reviews:
        return None
    return max(reviews, key=lambda row: int(row.get("version") or 0))


def _show_review_result(review_document: dict[str, Any]) -> None:
    label = review_status_label(review_document)
    counts = review_document.get("finding_counts")
    counts = counts if isinstance(counts, dict) else {}
    found = int(counts.get("found") or 0)
    needs_review = int(counts.get("needs_review") or 0)
    missing = int(counts.get("missing_deal_fact") or 0)

    if label == "Looks good":
        st.success("Looks good — the verified Deal facts checked by CommandCore were found in this contract.")
    elif label == "Missing Deal facts":
        st.warning("CommandCore needs more Deal information before this review can be complete.")
    else:
        st.warning("Needs attention — one or more verified Deal facts were not found exactly in this contract.")

    cols = st.columns(3)
    cols[0].metric("Matched", found)
    cols[1].metric("Needs attention", needs_review)
    cols[2].metric("Missing Deal facts", missing)

    findings = review_document.get("findings")
    findings = findings if isinstance(findings, list) else []
    attention = [row for row in findings if _text(row.get("status")) != "found"]
    if attention:
        with st.expander("See what needs attention", expanded=True):
            for finding in attention:
                st.markdown(f"**{_text(finding.get('label')) or 'Deal fact'}**")
                expected = _text(finding.get("expected_value"))
                if expected:
                    st.caption(f"Expected from Deal: {expected}")
                st.write(_text(finding.get("detail")))
    with st.expander("Full review details"):
        st.dataframe(findings, use_container_width=True, hide_index=True)
        st.caption(
            "This review compares document text with verified Deal facts. It does not make a legal conclusion, approve terms, or sign anything."
        )


def run_live_contract_review(
    *,
    deal: dict[str, Any],
    deal_id: str,
    source_document: dict[str, Any],
    documents: list[dict[str, Any]],
    save_related: Any,
    get_supabase: Any,
) -> dict[str, Any]:
    source_document_id = _text(source_document.get("id"))
    object_path = _text(
        source_document.get("storage_object_path")
        or source_document.get("object_path")
        or source_document.get("storage_path")
    )
    if not source_document_id:
        raise ContractWorkspaceError("This contract record is missing its document ID.")
    if not object_path:
        raise ContractWorkspaceError("The stored contract file could not be located for review.")

    deal_links = _links(deal)
    client = get_supabase()

    def linked_record(entity: str, record_id: str) -> dict[str, Any] | None:
        if not record_id:
            return None
        response = client.functions.invoke(
            "commandcore-crm-core",
            {"body": {"action": "get", "entity": entity, "id": record_id}},
        )
        payload = response if isinstance(response, dict) else getattr(response, "data", None)
        record = payload.get("record") if isinstance(payload, dict) else None
        return record if isinstance(record, dict) else None

    seller = linked_record("contacts", _text(deal_links.get("contact_id")))
    property_record = linked_record("properties", _text(deal_links.get("property_id")))
    file_content = ContractFileStore(client).download(object_path)
    review, review_document, activity = build_contract_review_package(
        deal_id=deal_id,
        deal=deal,
        seller=seller,
        property_record=property_record,
        source_document=source_document,
        file_content=file_content,
        review_version=_next_review_version(documents, source_document_id),
    )
    if not save_related("documents", deal_id, review_document):
        raise ContractWorkspaceError("The review finished, but CommandCore could not save the review result.")
    save_related("activities", deal_id, activity)
    return review_document


def render_live_contract_review(
    *,
    deal: dict[str, Any],
    deal_id: str,
    selected: dict[str, Any],
    documents: list[dict[str, Any]],
    save_related: Any,
    get_supabase: Any,
) -> None:
    document_id = _text(selected.get("id"))
    latest = _latest_review(documents, document_id)
    if latest:
        st.markdown("#### Latest review")
        _show_review_result(latest)

    button_label = "Review Again" if latest else "Review Contract Now"
    st.caption("CommandCore will compare this contract with the verified facts already saved on the Deal.")
    if st.button(button_label, type="primary", key=f"live_contract_review_{deal_id}_{document_id}"):
        try:
            result = run_live_contract_review(
                deal=deal,
                deal_id=deal_id,
                source_document=selected,
                documents=documents,
                save_related=save_related,
                get_supabase=get_supabase,
            )
        except ContractReaderError as exc:
            st.error(str(exc))
            if "scanned" in str(exc).casefold() or "image-only" in str(exc).casefold():
                st.info("Upload a text-readable PDF/DOCX version or run OCR first. CommandCore will not pretend a scanned contract was reviewed.")
        except ContractWorkspaceError as exc:
            st.error(str(exc))
        except Exception:
            st.error("CommandCore could not complete this review. Nothing was approved, signed, or sent.")
        else:
            _show_review_result(result)
