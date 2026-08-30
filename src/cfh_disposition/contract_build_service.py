from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .contract_deal_facts import contract_prep_document
from .contract_generation_pipeline import (
    ContractGenerationError,
    generate_and_store_contract,
    is_illinois_cfd,
    select_exact_approved_template,
)
from .contract_workspace import CONTRACT_BUCKET

SaveRelated = Callable[[str, str, dict[str, Any]], bool]
ListDocuments = Callable[[], list[dict[str, Any]]]


class ContractBuildState(StrEnum):
    GENERATED = "generated"
    ALREADY_CURRENT = "already_current"
    MISSING_FACTS = "missing_facts"
    COORDINATOR_REQUIRED = "coordinator_required"


@dataclass(frozen=True, slots=True)
class ContractBuildOutcome:
    state: ContractBuildState
    message: str
    generated_document: dict[str, Any] | None = None
    prep_document: dict[str, Any] | None = None
    history_saved: bool = True


def _text(value: Any) -> str:
    return str(value or "").strip()


def _links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def _next_prep_version(documents: list[dict[str, Any]], contract_type: str) -> int:
    versions: list[int] = []
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


def _active_prep_document(documents: list[dict[str, Any]], contract_type: str) -> dict[str, Any] | None:
    terminal = {"approved", "completed", "executed", "fully_executed"}
    matches = [
        document
        for document in documents
        if _text(document.get("document_type")) == "contract_prep_facts"
        and _text(document.get("contract_type")) == contract_type
        and _text(document.get("status")).casefold() not in terminal
    ]
    return matches[-1] if matches else None


def _facts_fingerprint(facts: dict[str, Any]) -> str:
    payload = json.dumps(facts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _saved_prep(
    documents: list[dict[str, Any]],
    *,
    contract_type: str,
    version: int,
    preferred_id: str,
) -> dict[str, Any] | None:
    if preferred_id:
        for document in documents:
            if _text(document.get("id")) == preferred_id:
                return document
    matches = [
        document
        for document in documents
        if _text(document.get("document_type")) == "contract_prep_facts"
        and _text(document.get("contract_type")) == contract_type
        and int(document.get("version") or 0) == version
    ]
    return matches[-1] if matches else None


def _same_generated_contract(
    documents: list[dict[str, Any]],
    *,
    deal_id: str,
    contract_type: str,
    template_id: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    for document in reversed(documents):
        if _text(document.get("document_type")) != "generated_contract":
            continue
        if _text(document.get("contract_type")) != contract_type:
            continue
        if _text(_links(document).get("deal_id") or document.get("deal_id")) != deal_id:
            continue
        provenance = document.get("generation_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        if _text(document.get("approved_legal_template_id")) != template_id:
            continue
        if _text(provenance.get("facts_fingerprint")) != fingerprint:
            continue
        return document
    return None


def _rollback_generated_upload(client: Any, object_path: str) -> None:
    if not object_path:
        return
    try:
        client.storage.from_(CONTRACT_BUCKET).remove([object_path])
    except Exception:
        pass


def build_contract_for_deal(
    *,
    client: Any,
    deal: dict[str, Any],
    deal_id: str,
    seller: dict[str, Any] | None,
    property_record: dict[str, Any] | None,
    contract_type: str,
    documents: list[dict[str, Any]],
    save_related: SaveRelated,
    list_documents: ListDocuments,
) -> ContractBuildOutcome:
    if not contract_type.strip():
        raise ContractGenerationError("Choose or enter the contract package before building.")

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
        raise ContractGenerationError("CommandCore could not save the verified Deal facts for contract preparation.")

    missing = prepared.get("missing_facts")
    if isinstance(missing, list) and missing:
        return ContractBuildOutcome(
            state=ContractBuildState.MISSING_FACTS,
            message="Complete these Deal facts first: " + ", ".join(str(item) for item in missing) + ".",
            prep_document=prepared,
        )

    refreshed = list_documents()
    saved_prep = _saved_prep(
        refreshed,
        contract_type=contract_type,
        version=int(prepared.get("version") or 1),
        preferred_id=_text(prepared.get("id")),
    )
    if saved_prep is None:
        raise ContractGenerationError("The verified contract facts were saved, but CommandCore could not reload their CRM record.")

    facts = saved_prep.get("facts") if isinstance(saved_prep.get("facts"), dict) else {}
    if not is_illinois_cfd(contract_type):
        return ContractBuildOutcome(
            state=ContractBuildState.COORDINATOR_REQUIRED,
            message="This approved contract package still uses the existing coordinator while its document renderer is connected.",
            prep_document=saved_prep,
        )

    template = select_exact_approved_template(
        refreshed,
        contract_type=contract_type,
        state=_text(facts.get("state")),
    )
    template_id = _text(template.get("id"))
    fingerprint = _facts_fingerprint(facts)
    already_current = _same_generated_contract(
        refreshed,
        deal_id=deal_id,
        contract_type=contract_type,
        template_id=template_id,
        fingerprint=fingerprint,
    )
    if already_current:
        return ContractBuildOutcome(
            state=ContractBuildState.ALREADY_CURRENT,
            message="The current Deal facts and approved template already have a generated contract. No duplicate version was created.",
            generated_document=already_current,
            prep_document=saved_prep,
        )

    generated = generate_and_store_contract(
        client=client,
        deal_id=deal_id,
        facts_document=saved_prep,
        all_documents=refreshed,
    )
    provenance = generated.document_record.get("generation_provenance")
    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    provenance["facts_fingerprint"] = fingerprint
    generated.document_record["generation_provenance"] = provenance

    if not save_related("documents", deal_id, generated.document_record):
        _rollback_generated_upload(client, _text(generated.document_record.get("storage_object_path")))
        raise ContractGenerationError(
            "The contract file was generated, but CommandCore could not attach it to the Deal. The private upload was rolled back when possible."
        )

    history_saved = save_related("activities", deal_id, generated.activity_record)
    saved_prep_update = {
        **saved_prep,
        "status": "generated_for_review",
        "contract_coordination_status": "document_generated",
        "approved_legal_template_id": generated.template_id,
        "generated_document_storage_path": generated.document_record.get("storage_object_path"),
        "insurance_version": generated.insurance_version,
        "facts_fingerprint": fingerprint,
        "document_assembled": True,
        "signing_started": False,
        "external_action_started": False,
    }
    save_related("documents", deal_id, saved_prep_update)

    message = "Contract generated privately and attached to this Deal for review. Nothing was signed or sent."
    if not history_saved:
        message += " The document is saved, but the Deal-history entry needs a retry."
    return ContractBuildOutcome(
        state=ContractBuildState.GENERATED,
        message=message,
        generated_document=generated.document_record,
        prep_document=saved_prep_update,
        history_saved=history_saved,
    )
