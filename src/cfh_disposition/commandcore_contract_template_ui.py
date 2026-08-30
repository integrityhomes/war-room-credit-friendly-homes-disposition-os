# ruff: noqa: I001
from __future__ import annotations

from typing import Any

import streamlit as st

from .contract_template_library import next_template_version, template_record, upload_template_file
from .contract_workspace import CONTRACT_BUCKET, ContractFile, ContractWorkspaceError


APPROVED_TEMPLATE_STATUSES = {"approved", "active", "owner_approved"}
TEMPLATE_DOCUMENT_TYPES = {"contract_template", "approved_legal_template"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _crm_call(get_supabase: Any, payload: dict[str, Any]) -> dict[str, Any]:
    response = get_supabase().functions.invoke("commandcore-crm-core", {"body": payload})
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    return data if isinstance(data, dict) else {}


def _all_documents(get_supabase: Any) -> list[dict[str, Any]]:
    result = _crm_call(get_supabase, {"action": "list", "entity": "documents", "limit": 500})
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def _linked_property_state(deal: dict[str, Any], get_supabase: Any) -> str:
    links = deal.get("links") if isinstance(deal.get("links"), dict) else {}
    property_id = _text(links.get("property_id"))
    if not property_id:
        return ""
    result = _crm_call(get_supabase, {"action": "get", "entity": "properties", "id": property_id})
    record = result.get("record")
    if not isinstance(record, dict):
        return ""
    return _text(record.get("state")).upper()


def _template_rows(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        document
        for document in documents
        if _text(document.get("document_type")) in TEMPLATE_DOCUMENT_TYPES
    ]


def _latest_template(
    documents: list[dict[str, Any]], *, contract_type: str, state: str
) -> dict[str, Any] | None:
    matches = [
        document
        for document in _template_rows(documents)
        if _text(document.get("contract_type")).lower() == contract_type.strip().lower()
        and _text(document.get("state")).lower() == state.strip().lower()
    ]
    if not matches:
        return None

    def version_value(document: dict[str, Any]) -> int:
        try:
            return int(document.get("version") or 0)
        except (TypeError, ValueError):
            return 0

    return max(matches, key=version_value)


def _approval_label(document: dict[str, Any]) -> str:
    if document.get("approved_for_use") is True and (
        document.get("legal_approved") is True
        or _text(document.get("legal_review_status")).lower() == "approved"
    ):
        return "Approved for use"
    status = _text(document.get("status")).lower()
    if status in APPROVED_TEMPLATE_STATUSES:
        return "Approved"
    if status == "needs_legal_approval":
        return "Needs legal approval"
    return _text(document.get("status")) or "Pending"


def _save_global_document(get_supabase: Any, record: dict[str, Any]) -> bool:
    result = _crm_call(
        get_supabase,
        {"action": "upsert", "entity": "documents", "record": record},
    )
    return bool(result.get("ok"))


def _upload_template(
    *,
    get_supabase: Any,
    documents: list[dict[str, Any]],
    contract_type: str,
    state: str,
    uploaded: Any,
    change_note: str,
) -> int:
    contract_type = contract_type.strip()
    state = state.strip().upper()
    if not contract_type:
        raise ContractWorkspaceError("Enter the contract package name.")
    if not state:
        raise ContractWorkspaceError("Enter the state or jurisdiction.")

    version = next_template_version(
        documents,
        contract_type=contract_type,
        state=state,
    )
    prior = _latest_template(documents, contract_type=contract_type, state=state)
    file = ContractFile(
        file_name=str(uploaded.name),
        content=uploaded.getvalue(),
        content_type=str(uploaded.type or ""),
    )
    stored = upload_template_file(
        client=get_supabase(),
        contract_type=contract_type,
        state=state,
        version=version,
        file=file,
    )
    record = template_record(
        contract_type=contract_type,
        state=state,
        version=version,
        stored=stored,
        prior_template_id=_text(prior.get("id")) if prior else "",
        change_note=change_note,
    )
    if _save_global_document(get_supabase, record):
        return version

    try:
        get_supabase().storage.from_(CONTRACT_BUCKET).remove([stored.object_path])
    except Exception:
        pass
    raise ContractWorkspaceError(
        "The template file uploaded, but CommandCore could not save the version record. "
        "The upload was rolled back when possible."
    )


def render_contract_template_library(
    *,
    deal: dict[str, Any],
    deal_id: str,
    get_supabase: Any,
) -> None:
    st.write("Manage changing contract templates without replacing the approved version by accident.")
    st.caption(
        "Every new DOCX is saved as a new version and starts in Needs Legal Approval. "
        "Uploading a version does not make it active or approved for use."
    )

    try:
        documents = _all_documents(get_supabase)
    except Exception:
        st.error("CommandCore could not load the contract template library right now.")
        return

    default_package = _text(deal.get("contract_type"))
    default_state = ""
    try:
        default_state = _linked_property_state(deal, get_supabase)
    except Exception:
        default_state = ""

    package_names = sorted(
        {
            _text(document.get("contract_type"))
            for document in _template_rows(documents)
            if _text(document.get("contract_type"))
        }
    )
    if default_package and default_package not in package_names:
        package_names.insert(0, default_package)

    with st.container(border=True):
        st.markdown("#### Add a template version")
        if package_names:
            package_options = [*package_names, "New package…"]
            selected = st.selectbox(
                "Contract package",
                package_options,
                index=package_options.index(default_package) if default_package in package_options else 0,
                key=f"template_package_{deal_id}",
            )
            if selected == "New package…":
                contract_type = st.text_input(
                    "New package name",
                    key=f"template_new_package_{deal_id}",
                ).strip()
            else:
                contract_type = selected
        else:
            contract_type = st.text_input(
                "Contract package",
                value=default_package,
                key=f"template_package_text_{deal_id}",
            ).strip()

        state = st.text_input(
            "State / jurisdiction",
            value=default_state,
            max_chars=40,
            key=f"template_state_{deal_id}",
        ).strip().upper()
        uploaded = st.file_uploader(
            "New template version (.docx)",
            type=["docx"],
            key=f"template_upload_{deal_id}",
        )
        change_note = st.text_area(
            "What changed?",
            placeholder="Example: Updated insurance clause after attorney review.",
            height=80,
            key=f"template_change_note_{deal_id}",
        )

        next_version = None
        if contract_type and state:
            next_version = next_template_version(
                documents,
                contract_type=contract_type,
                state=state,
            )
            latest = _latest_template(documents, contract_type=contract_type, state=state)
            if latest:
                st.caption(
                    f"Current latest version: v{_text(latest.get('version')) or '—'} · "
                    f"{_approval_label(latest)}. New upload will be v{next_version}."
                )
            else:
                st.caption(f"This will be the first saved template for this package: v{next_version}.")

        if st.button(
            "Save New Template Version",
            type="primary",
            disabled=uploaded is None or not contract_type or not state,
            key=f"save_template_{deal_id}",
        ):
            try:
                version = _upload_template(
                    get_supabase=get_supabase,
                    documents=documents,
                    contract_type=contract_type,
                    state=state,
                    uploaded=uploaded,
                    change_note=change_note,
                )
            except ContractWorkspaceError as exc:
                st.error(str(exc))
            except Exception:
                st.error("CommandCore could not save this template version. The active template was not changed.")
            else:
                st.success(
                    f"Template v{version} saved. It is waiting for legal/owner approval and is not active yet."
                )
                st.rerun()

    st.markdown("#### Template library")
    rows = _template_rows(documents)
    if not rows:
        st.info("No contract templates have been saved in CommandCore yet.")
        return

    rows = sorted(
        rows,
        key=lambda document: (
            _text(document.get("contract_type")).lower(),
            _text(document.get("state")).lower(),
            -(int(document.get("version") or 0) if str(document.get("version") or "").isdigit() else 0),
        ),
    )
    table = [
        {
            "Package": _text(document.get("contract_type")),
            "State": _text(document.get("state")),
            "Version": f"v{_text(document.get('version')) or '—'}",
            "Approval": _approval_label(document),
            "What changed": _text(document.get("change_note")),
            "Created": document.get("created_at"),
        }
        for document in rows
    ]
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(
        "Older approved versions remain available until a newer version completes the required approval process."
    )
