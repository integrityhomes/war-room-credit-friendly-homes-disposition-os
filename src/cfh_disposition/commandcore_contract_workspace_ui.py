from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from .commandcore_contract_review_ui import render_live_contract_review
from .contract_deal_facts import ContractFactsError, contract_prep_document
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


TERMINAL_PREP_STATUSES = {
    "package_ready",
    "approved",
    "completed",
    "executed",
    "fully_executed",
}
APPROVED_TEMPLATE_STATUSES = {"approved", "active", "owner_approved"}
APPROVED_TEMPLATE_TYPES = {"approved_legal_template", "contract_template"}


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


def _next_prep_version(documents: list[dict[str, Any]], contract_type: str) -> int:
    versions = []
    for document in documents:
        if _text(document.get("document_type")) != "contract_prep_facts":
            continue
        if _text(document.get("contract_type")) != contract_type:
            continue
        try:
            versions.append(int(document.get("version") or 0))
        except (TypeError, ValueError):
            continue
    return max(versions, default=0) + 1


def _crm_call(get_supabase: GetSupabase, payload: dict[str, Any]) -> dict[str, Any]:
    response = get_supabase().functions.invoke("commandcore-crm-core", {"body": payload})
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    return data if isinstance(data, dict) else {}


def _linked_record(get_supabase: GetSupabase, entity: str, record_id: str) -> dict[str, Any] | None:
    if not record_id:
        return None
    result = _crm_call(get_supabase, {"action": "get", "entity": entity, "id": record_id})
    record = result.get("record")
    return record if isinstance(record, dict) else None


def _all_documents(get_supabase: GetSupabase) -> list[dict[str, Any]]:
    result = _crm_call(get_supabase, {"action": "list", "entity": "documents", "limit": 500})
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def _approved_contract_types(get_supabase: GetSupabase) -> list[str]:
    types: set[str] = set()
    for document in _all_documents(get_supabase):
        if _text(document.get("document_type")) not in APPROVED_TEMPLATE_TYPES:
            continue
        if _text(document.get("status")).lower() not in APPROVED_TEMPLATE_STATUSES:
            continue
        if document.get("approved_for_use") is not True:
            continue
        legal_ok = (
            document.get("legal_approved") is True
            or _text(document.get("legal_review_status")).lower() == "approved"
        )
        if not legal_ok:
            continue
        contract_type = _text(document.get("contract_type"))
        if contract_type:
            types.add(contract_type)
    return sorted(types)


def _active_prep_document(documents: list[dict[str, Any]], contract_type: str) -> dict[str, Any] | None:
    matches = [
        document
        for document in documents
        if _text(document.get("document_type")) == "contract_prep_facts"
        and _text(document.get("contract_type")) == contract_type
        and _text(document.get("status")).lower() not in TERMINAL_PREP_STATUSES
    ]
    return matches[-1] if matches else None


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
        raise ContractWorkspaceError(
            "The file uploaded, but CommandCore could not attach it to the Deal. "
            "The upload was rolled back when possible."
        )
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


def _selected_contract_type(deal: dict[str, Any], get_supabase: GetSupabase, deal_id: str) -> str:
    current = _text(deal.get("contract_type"))
    approved_types = _approved_contract_types(get_supabase)
    options = list(approved_types)
    if current and current not in options:
        options.insert(0, current)

    if options:
        options.append("Other / not listed")
        selected = st.selectbox(
            "Contract package",
            options,
            index=options.index(current) if current in options else 0,
            key=f"contract_package_{deal_id}",
            help=(
                "Choose the legal document package explicitly. "
                "CommandCore will not infer this from the property state."
            ),
        )
        if selected != "Other / not listed":
            return selected

    return st.text_input(
        "Exact contract package name",
        value="" if options else current,
        key=f"contract_package_other_{deal_id}",
        help=(
            "Enter the package name exactly. An unapproved package will be blocked until an approved template exists."
        ),
    ).strip()


def _prepare_contract_from_deal(
    *,
    deal: dict[str, Any],
    deal_id: str,
    documents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    contract_type: str,
    save_related: SaveRelated,
    create_work_request: CreateWorkRequest,
    get_supabase: GetSupabase,
) -> None:
    if not contract_type:
        raise ContractFactsError("Choose or enter the contract package before building.")

    deal_links = _links(deal)
    seller = _linked_record(get_supabase, "contacts", _text(deal_links.get("contact_id")))
    property_record = _linked_record(get_supabase, "properties", _text(deal_links.get("property_id")))
    prepared = contract_prep_document(
        deal_id=deal_id,
        deal={**deal, "contract_type": contract_type},
        seller=seller,
        property_record=property_record,
    )

    existing = _active_prep_document(documents, contract_type)
    if existing:
        prepared["id"] = existing.get("id")
        prepared["version"] = existing.get("version") or 1
    else:
        prepared["version"] = _next_prep_version(documents, contract_type)

    if not save_related("documents", deal_id, prepared):
        raise ContractWorkspaceError("CommandCore could not save the verified Deal facts for contract preparation.")

    missing = prepared.get("missing_facts", [])
    if isinstance(missing, list) and missing:
        readable = ", ".join(str(item) for item in missing)
        st.warning(f"Contract preparation is saved but blocked. Complete these Deal facts first: {readable}.")
        return

    coordinator_ok = True
    try:
        response = get_supabase().functions.invoke(
            "commandcore-contract-document-coordinator",
            {"body": {"apply": True}},
        )
        if isinstance(response, dict):
            coordinator_ok = bool(response.get("ok", True))
        else:
            data = getattr(response, "data", None)
            coordinator_ok = bool(data.get("ok", True)) if isinstance(data, dict) else True
    except Exception:
        coordinator_ok = False

    if not coordinator_ok:
        st.info(
            "The verified Deal facts are saved. The document coordinator did not confirm this run, "
            "so the normal contract workflow can retry without losing the prepared facts."
        )

    create_work_request(
        deal,
        deal_id,
        tasks,
        "prepare_contract",
        "Prepare contract package for approval",
    )


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
        st.write("Prepare a contract package using verified Deal facts and the approved legal-template workflow.")
        st.caption(
            "You choose the contract package. CommandCore gathers known Deal facts, identifies anything missing, "
            "and only releases complete facts to an approved template."
        )
        try:
            contract_type = _selected_contract_type(deal, get_supabase, deal_id)
        except Exception:
            contract_type = _text(deal.get("contract_type"))
            st.info("Approved template choices could not be loaded. You can still use the Deal's saved contract type.")
        if st.button("Build Contract", type="primary", key=f"build_contract_{deal_id}"):
            try:
                _prepare_contract_from_deal(
                    deal=deal,
                    deal_id=deal_id,
                    documents=documents,
                    tasks=tasks,
                    contract_type=contract_type,
                    save_related=save_related,
                    create_work_request=create_work_request,
                    get_supabase=get_supabase,
                )
            except (ContractFactsError, ContractWorkspaceError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("CommandCore could not prepare this contract package. Nothing was signed or sent.")

    with review_tab:
        st.write("Review a contract against the verified facts already saved on this Deal.")
        reviewable = _reviewable_documents(documents)
        if not reviewable:
            st.info("Upload a contract first. Once it is attached to this Deal, you can review it here.")
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
            render_live_contract_review(
                deal=deal,
                deal_id=deal_id,
                selected=options[selected_label],
                documents=documents,
                save_related=save_related,
                get_supabase=get_supabase,
            )

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
