# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from .contract_deal_facts import ContractFactsError, assemble_contract_facts, contract_prep_document
from .contract_reader import ContractReaderError, review_contract
from .contract_review_facts import review_facts_from_verified_contract_facts
from .contract_review_records import contract_review_activity, contract_review_document
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


def _run_contract_review(
    *,
    deal: dict[str, Any],
    deal_id: str,
    document: dict[str, Any],
    tasks: list[dict[str, Any]],
    save_related: SaveRelated,
    get_supabase: GetSupabase,
) -> dict[str, Any]:
    document_id = _text(document.get("id"))
    file_name = _text(document.get("name"))
    object_path = _text(document.get("storage_object_path"))
    if not document_id:
        raise ContractWorkspaceError("This contract is missing its document ID. Upload it again before review.")
    if not object_path:
        raise ContractWorkspaceError("This contract version does not have a private stored file to review.")

    deal_links = _links(deal)
    seller = _linked_record(get_supabase, "contacts", _text(deal_links.get("contact_id")))
    property_record = _linked_record(get_supabase, "properties", _text(deal_links.get("property_id")))
    verified_facts, _missing = assemble_contract_facts(
        deal=deal,
        seller=seller,
        property_record=property_record,
    )
    reader_facts = review_facts_from_verified_contract_facts(verified_facts)
    file_bytes = ContractFileStore(get_supabase()).download(object_path)
    review = review_contract(file_name, file_bytes, reader_facts)
    review_record = contract_review_document(
        deal_id=deal_id,
        source_document_id=document_id,
        source_document_version=document.get("version") or "",
        source_file_name=file_name,
        review=review,
    )
    if not save_related("documents", deal_id, review_record):
        raise ContractWorkspaceError("CommandCore completed the review but could not save the findings to this Deal.")
    activity = contract_review_activity(source_file_name=file_name, review_document=review_record)
    save_related("activities", deal_id, activity)

    counts = review_record.get("finding_counts")
    counts = counts if isinstance(counts, dict) else {}
    needs_attention = int(counts.get("needs_review") or 0) + int(counts.get("missing_deal_fact") or 0)
    if needs_attention and not _review_task_exists(tasks, document_id):
        save_related(
            "tasks",
            deal_id,
            {
                "title": "Review contract findings",
                "work_type": "review_contract",
                "task_type": "deal_lifecycle_request",
                "status": "open",
                "priority": "high",
                "source": "commandcore-contract-reader",
                "external_action_started": False,
                "links": {"document_id": document_id},
            },
        )
    return review_record


def _show_review_result(review_record: dict[str, Any]) -> None:
    counts = review_record.get("finding_counts")
    counts = counts if isinstance(counts, dict) else {}
    found = int(counts.get("found") or 0)
    needs_review = int(counts.get("needs_review") or 0)
    missing = int(counts.get("missing_deal_fact") or 0)

    if not needs_review and not missing:
        st.success(f"Looks good so far — {found} verified Deal fact(s) were found in this contract.")
    else:
        st.warning(f"Needs attention — {needs_review + missing} item(s) should be checked before approval.")
        if missing:
            st.info(f"{missing} Deal fact(s) are missing in CommandCore and need to be completed first.")

    st.caption(
        "This is a business-fact comparison, not legal advice or legal approval. "
        "CommandCore did not sign, send, or change the contract."
    )
    findings = review_record.get("findings")
    findings = findings if isinstance(findings, list) else []
    if findings:
        labels = {
            "found": "Found",
            "needs_review": "Check this",
            "missing_deal_fact": "Missing Deal fact",
        }
        rows = [
            {
                "Item": _text(finding.get("label")),
                "Status": labels.get(_text(finding.get("status")), _text(finding.get("status"))),
                "Expected from Deal": _text(finding.get("expected_value")) or "—",
                "What CommandCore found": _text(finding.get("detail")),
            }
            for finding in findings
            if isinstance(finding, dict)
        ]
        with st.expander("Review details", expanded=bool(needs_review or missing)):
            st.dataframe(rows, use_container_width=True, hide_index=True)


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
        "Upload, build, and review contracts from this Deal. Files stay private and versioned, and CommandCore keeps the work tied to this Deal."
    )

    upload_tab, build_tab, review_tab, versions_tab = st.tabs(
        ["Upload Contract", "Build Contract", "Review Contract", "Version History"]
    )

    with upload_tab:
        st.write("Add a new or revised contract to this Deal.")
        uploaded = st.file_uploader(
            "Contract file",
            type=["pdf", "docx"],
            key=f"contract_upload_{deal_id}",
            help="CommandCore keeps every upload as a separate version so earlier contracts are never overwritten.",
        )
        next_version = _next_version(documents, DocumentPurpose.UPLOADED_CONTRACT)
        st.caption(f"Next version: {next_version}")
        if st.button(
            "Upload Contract",
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
                st.success("Contract uploaded and saved to this Deal.")
                st.rerun()

    with build_tab:
        st.write("Build a contract using the verified information already saved on this Deal.")
        st.caption(
            "You choose the contract package. CommandCore fills known Deal facts, shows anything missing, and only uses an approved legal template."
        )
        try:
            contract_type = _selected_contract_type(deal, get_supabase, deal_id)
        except Exception:
            contract_type = _text(deal.get("contract_type"))
            st.info("Template choices could not be loaded. You can still use the contract type already saved on this Deal.")
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
        st.write("Compare a contract to the verified facts already saved on this Deal.")
        reviewable = _reviewable_documents(documents)
        if not reviewable:
            st.info("Upload a contract first. Then you can review it here without leaving CommandCore.")
        else:
            options = {
                f"{_text(document.get('name')) or 'Contract'} · Version {_text(document.get('version')) or '—'}": document
                for document in reviewable
            }
            selected_label = st.selectbox(
                "Choose contract",
                list(options),
                key=f"contract_review_select_{deal_id}",
            )
            selected = options[selected_label]
            if st.button("Review Now", type="primary", key=f"review_contract_{deal_id}"):
                try:
                    review_record = _run_contract_review(
                        deal=deal,
                        deal_id=deal_id,
                        document=selected,
                        tasks=tasks,
                        save_related=save_related,
                        get_supabase=get_supabase,
                    )
                except (ContractFactsError, ContractReaderError, ContractWorkspaceError) as exc:
                    st.error(str(exc))
                except Exception:
                    st.error("CommandCore could not review this contract. Nothing was signed, sent, or changed.")
                else:
                    st.session_state[f"contract_review_result_{deal_id}"] = review_record

            current_result = st.session_state.get(f"contract_review_result_{deal_id}")
            if isinstance(current_result, dict):
                _show_review_result(current_result)

            prior_reviews = [
                document
                for document in documents
                if _text(document.get("document_type")) == DocumentPurpose.CONTRACT_REVIEW.value
                and _text(document.get("source_document_id")) == _text(selected.get("id"))
            ]
            if prior_reviews:
                latest = prior_reviews[-1]
                st.markdown("#### Latest saved review")
                _show_review_result(latest)

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
            st.caption("Earlier contract versions stay preserved; stored file paths remain private.")