from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from .contract_workspace import (
    CONTRACT_BUCKET,
    ContractFile,
    ContractFileStore,
    ContractWorkspaceError,
    DocumentPurpose,
    document_record,
)

SaveRelated = Callable[[str, str, dict[str, Any]], bool]
CreateWorkRequest = Callable[[dict[str, Any], str, list[dict[str, Any]], str, str], None]
GetSupabase = Callable[[], Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def _next_version(documents: list[dict[str, Any]], purpose: DocumentPurpose) -> int:
    versions = []
    for document in documents:
        if _text(document.get("document_type")) != purpose.value:
            continue
        try:
            versions.append(int(document.get("version") or 0))
        except (TypeError, ValueError):
            continue
    return max(versions, default=0) + 1


def _review_task_exists(tasks: list[dict[str, Any]], document_id: str) -> bool:
    for task in tasks:
        status = _text(task.get("status")).lower()
        if status in {"done", "completed", "closed", "cancelled", "canceled"}:
            continue
        if _text(task.get("work_type")) != "review_contract":
            continue
        if _text(_links(task).get("document_id")) == document_id:
            return True
    return False


def _upload_contract(
    *,
    deal_id: str,
    documents: list[dict[str, Any]],
    uploaded: Any,
    save_related: SaveRelated,
    get_supabase: GetSupabase,
) -> None:
    purpose = DocumentPurpose.UPLOADED_CONTRACT
    version = _next_version(documents, purpose)
    content = uploaded.getvalue()
    file = ContractFile(
        file_name=str(uploaded.name),
        content=content,
        content_type=str(uploaded.type or ""),
    )
    store = ContractFileStore(get_supabase())
    stored = store.upload(deal_id=deal_id, purpose=purpose, version=version, file=file)
    record = document_record(
        deal_id=deal_id,
        purpose=purpose,
        stored=stored,
        version=version,
    )
    if not save_related("documents", deal_id, record):
        try:
            get_supabase().storage.from_(CONTRACT_BUCKET).remove([stored.object_path])
        except Exception:
            pass
        raise ContractWorkspaceError("The file uploaded, but CommandCore could not attach it to the Deal. The upload was rolled back when possible.")
    save_related(
        "activities",
        deal_id,
        {
            "activity_type": "contract_uploaded",
            "summary": f"Contract uploaded as version {version}: {stored.file_name}",
            "source": "commandcore-contract-workspace",
            "details": {
                "document_type": purpose.value,
                "version": version,
                "storage_private": True,
            },
        },
    )


def _reviewable_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {
        DocumentPurpose.UPLOADED_CONTRACT.value,
        DocumentPurpose.GENERATED_CONTRACT.value,
        "executed_contract",
        "signed_contract",
    }
    return [document for document in documents if _text(document.get("document_type")) in allowed]


def render_contract_workspace(
    *,
    deal: dict[str, Any],
    deal_id: str,
    documents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    save_related: SaveRelated,
    create_work_request: CreateWorkRequest,
    get_supabase: GetSupabase,
) -> None:
    st.markdown("### Contract Workspace")
    st.caption(
        "Upload, prepare, and review contracts from this Deal. Files stay private and versioned. "
        "These controls do not sign agreements or change legal terms."
    )

    upload_tab, build_tab, review_tab, versions_tab = st.tabs(
        ["Upload Contract", "Build Contract", "Review Contract", "Version History"]
    )

    with upload_tab:
        uploaded = st.file_uploader(
            "Contract file",
            type=["pdf", "docx"],
            key=f"contract_upload_{deal_id}",
            help="Upload a new or revised contract. CommandCore keeps each upload as a separate immutable version.",
        )
        next_version = _next_version(documents, DocumentPurpose.UPLOADED_CONTRACT)
        st.caption(f"This upload will be saved as contract upload version {next_version}.")
        if st.button(
            "Upload to this Deal",
            type="primary",
            disabled=uploaded is None,
            key=f"save_contract_upload_{deal_id}",
        ):
            try:
                _upload_contract(
                    deal_id=deal_id,
                    documents=documents,
                    uploaded=uploaded,
                    save_related=save_related,
                    get_supabase=get_supabase,
                )
            except ContractWorkspaceError as exc:
                st.error(str(exc))
            except Exception:
                st.error("CommandCore could not upload this contract. Nothing was signed or sent.")
            else:
                st.success("Contract uploaded privately and attached to this Deal.")
                st.rerun()

    with build_tab:
        st.write("Prepare a contract package using the approved Deal facts and approved legal template workflow.")
        st.caption("Document preparation is separate from signing, binding, or changing approved legal terms.")
        if st.button("Build Contract", type="primary", key=f"build_contract_{deal_id}"):
            create_work_request(
                deal,
                deal_id,
                tasks,
                "prepare_contract",
                "Prepare contract package for approval",
            )

    with review_tab:
        reviewable = _reviewable_documents(documents)
        if not reviewable:
            st.info("Upload a contract first. Once it is attached to this Deal, it can be sent into contract review.")
        else:
            options = {
                f"{_text(document.get('name')) or 'Contract'} · v{_text(document.get('version')) or '—'}": document
                for document in reviewable
            }
            selected_label = st.selectbox(
                "Contract to review",
                list(options),
                key=f"contract_review_select_{deal_id}",
            )
            selected = options[selected_label]
            document_id = _text(selected.get("id"))
            if _review_task_exists(tasks, document_id):
                st.info("A review request is already open for this contract version.")
            elif st.button("Review Contract", type="primary", key=f"review_contract_{deal_id}"):
                saved = save_related(
                    "tasks",
                    deal_id,
                    {
                        "title": "Review contract against Deal facts",
                        "work_type": "review_contract",
                        "task_type": "deal_lifecycle_request",
                        "status": "open",
                        "priority": "high",
                        "source": "commandcore-contract-workspace",
                        "external_action_started": False,
                        "links": {"document_id": document_id},
                    },
                )
                if saved:
                    st.success("Contract review request added to this Deal.")
                    st.rerun()
                st.error("CommandCore could not create the contract review request.")

    with versions_tab:
        contract_rows = _reviewable_documents(documents)
        if not contract_rows:
            st.caption("No contract versions have been attached to this Deal yet.")
        else:
            table = [
                {
                    "File": _text(document.get("name")),
                    "Type": _text(document.get("document_type")),
                    "Version": document.get("version"),
                    "Status": _text(document.get("status")),
                    "Template": _text(document.get("template_family")),
                    "Template version": _text(document.get("template_version")),
                    "Created": document.get("created_at"),
                }
                for document in contract_rows
            ]
            st.dataframe(table, use_container_width=True, hide_index=True)
            st.caption("Stored file paths remain private; CommandCore does not expose public contract URLs.")
