from __future__ import annotations

import re
from typing import Any

from .contract_workspace import (
    CONTRACT_BUCKET,
    ContractFile,
    ContractFileStore,
    ContractWorkspaceError,
    DocumentPurpose,
    StoredContractFile,
    normalized_content_type,
    safe_file_name,
    validate_contract_file,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()


def template_object_path(
    *,
    contract_type: str,
    state: str,
    version: int,
    file_name: str,
) -> str:
    contract_slug = _slug(contract_type)
    state_slug = _slug(state)
    if not contract_slug:
        raise ContractWorkspaceError("Contract package name is required for a template.")
    if not state_slug:
        raise ContractWorkspaceError("Template state/jurisdiction is required.")
    if version < 1:
        raise ContractWorkspaceError("Template version must be 1 or higher.")
    return f"templates/{state_slug}/{contract_slug}/v{version}/{safe_file_name(file_name)}"


def next_template_version(
    documents: list[dict[str, Any]],
    *,
    contract_type: str,
    state: str,
) -> int:
    versions: list[int] = []
    for document in documents:
        if _text(document.get("document_type")) not in {"contract_template", "approved_legal_template"}:
            continue
        if _text(document.get("contract_type")).lower() != contract_type.strip().lower():
            continue
        if _text(document.get("state")).lower() != state.strip().lower():
            continue
        try:
            versions.append(int(document.get("version") or 0))
        except (TypeError, ValueError):
            continue
    return max(versions, default=0) + 1


def template_record(
    *,
    contract_type: str,
    state: str,
    version: int,
    stored: StoredContractFile,
    prior_template_id: str = "",
    change_note: str = "",
) -> dict[str, Any]:
    contract_type = contract_type.strip()
    state = state.strip().upper()
    if not contract_type:
        raise ContractWorkspaceError("Contract package name is required for a template.")
    if not state:
        raise ContractWorkspaceError("Template state/jurisdiction is required.")
    if version < 1:
        raise ContractWorkspaceError("Template version must be 1 or higher.")
    return {
        "name": stored.file_name,
        "document_type": "contract_template",
        "contract_type": contract_type,
        "template_family": contract_type,
        "state": state,
        "version": version,
        "template_version": f"v{version}",
        "status": "needs_legal_approval",
        "legal_review_status": "pending",
        "legal_approved": False,
        "approved_for_use": False,
        "owner_approved": False,
        "storage_bucket": CONTRACT_BUCKET,
        "storage_object_path": stored.object_path,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "prior_template_id": prior_template_id.strip() or None,
        "change_note": change_note.strip() or None,
        "immutable_version": True,
        "legal_terms_generated": False,
        "legal_terms_changed_by_commandcore": False,
        "signing_started": False,
        "external_action_started": False,
        "source": "commandcore-contract-template-library",
    }


def upload_template_file(
    *,
    client: Any,
    contract_type: str,
    state: str,
    version: int,
    file: ContractFile,
) -> StoredContractFile:
    validate_contract_file(file, DocumentPurpose.CONTRACT_TEMPLATE)
    store = ContractFileStore(client)
    store._ensure_bucket()
    object_path = template_object_path(
        contract_type=contract_type,
        state=state,
        version=version,
        file_name=file.file_name,
    )
    content_type = normalized_content_type(file.content_type)
    try:
        client.storage.from_(CONTRACT_BUCKET).upload(
            path=object_path,
            file=file.content,
            file_options={
                "content-type": content_type,
                "cache-control": "3600",
                "upsert": "false",
            },
        )
    except Exception as exc:
        raise ContractWorkspaceError("Could not store the contract template privately.") from exc
    return StoredContractFile(
        object_path=object_path,
        file_name=file.file_name,
        content_type=content_type,
        size_bytes=len(file.content),
    )
