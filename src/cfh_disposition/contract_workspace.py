# ruff: noqa: I001
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


CONTRACT_BUCKET = "commandcore-contract-documents"
CONTRACT_MAX_BYTES = 25 * 1024 * 1024
CONTRACT_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
CONTRACT_EXTENSIONS = {".pdf", ".docx"}
TEMPLATE_EXTENSIONS = {".docx"}


class ContractWorkspaceError(RuntimeError):
    """Raised when a contract workspace operation cannot safely continue."""


class DocumentPurpose(StrEnum):
    UPLOADED_CONTRACT = "uploaded_contract"
    CONTRACT_TEMPLATE = "contract_template"
    GENERATED_CONTRACT = "generated_contract"
    CONTRACT_REVIEW = "contract_review"


@dataclass(frozen=True, slots=True)
class ContractFile:
    file_name: str
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class StoredContractFile:
    object_path: str
    file_name: str
    content_type: str
    size_bytes: int


def normalized_content_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def validate_contract_file(file: ContractFile, purpose: DocumentPurpose) -> None:
    extension = Path(file.file_name).suffix.lower()
    content_type = normalized_content_type(file.content_type)
    allowed_extensions = TEMPLATE_EXTENSIONS if purpose == DocumentPurpose.CONTRACT_TEMPLATE else CONTRACT_EXTENSIONS
    if extension not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise ContractWorkspaceError(f"Only {allowed} files are allowed for this document type.")
    if content_type not in CONTRACT_MIME_TYPES:
        raise ContractWorkspaceError("Only PDF and DOCX contract files are allowed.")
    if not file.content:
        raise ContractWorkspaceError(f"{file.file_name} is empty.")
    if len(file.content) > CONTRACT_MAX_BYTES:
        raise ContractWorkspaceError(f"{file.file_name} is larger than 25 MB.")


def safe_file_name(file_name: str) -> str:
    extension = Path(file_name).suffix.lower()
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(file_name).stem).strip("-")[:80]
    return f"{stem or 'contract'}-{uuid4().hex}{extension}"


def contract_object_path(
    *,
    deal_id: str,
    purpose: DocumentPurpose,
    version: int,
    file_name: str,
) -> str:
    safe_deal = re.sub(r"[^a-zA-Z0-9_-]+", "-", deal_id).strip("-")
    if not safe_deal:
        raise ContractWorkspaceError("A Deal is required before a contract file can be stored.")
    if version < 1:
        raise ContractWorkspaceError("Document version must be 1 or higher.")
    return f"deals/{safe_deal}/{purpose.value}/v{version}/{safe_file_name(file_name)}"


def document_record(
    *,
    deal_id: str,
    purpose: DocumentPurpose,
    stored: StoredContractFile,
    version: int,
    template_family: str = "",
    template_version: str = "",
    prior_document_id: str = "",
) -> dict[str, Any]:
    if version < 1:
        raise ContractWorkspaceError("Document version must be 1 or higher.")
    if purpose == DocumentPurpose.CONTRACT_TEMPLATE and not template_family.strip():
        raise ContractWorkspaceError("Template family is required for contract templates.")
    return {
        "name": stored.file_name,
        "document_type": purpose.value,
        "status": "uploaded" if purpose != DocumentPurpose.CONTRACT_TEMPLATE else "needs_legal_approval",
        "version": version,
        "storage_bucket": CONTRACT_BUCKET,
        "storage_object_path": stored.object_path,
        "content_type": stored.content_type,
        "size_bytes": stored.size_bytes,
        "template_family": template_family.strip() or None,
        "template_version": template_version.strip() or None,
        "prior_document_id": prior_document_id.strip() or None,
        "immutable_version": True,
        "legal_terms_generated": False,
        "legal_terms_changed": False,
        "signing_started": False,
        "external_action_started": False,
        "links": {"deal_id": deal_id},
    }


class ContractFileStore:
    """Private Supabase Storage adapter for contract/document bytes."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            bucket = self._client.storage.get_bucket(CONTRACT_BUCKET)
            bucket_public = bucket.get("public", False) if isinstance(bucket, dict) else getattr(bucket, "public", False)
            if bool(bucket_public):
                raise ContractWorkspaceError("Contract storage bucket must remain private.")
        except ContractWorkspaceError:
            raise
        except Exception:
            try:
                self._client.storage.create_bucket(
                    CONTRACT_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": sorted(CONTRACT_MIME_TYPES),
                        "file_size_limit": CONTRACT_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise ContractWorkspaceError("Could not create the private contract storage bucket.") from exc
        self._bucket_ready = True

    def upload(
        self,
        *,
        deal_id: str,
        purpose: DocumentPurpose,
        version: int,
        file: ContractFile,
    ) -> StoredContractFile:
        validate_contract_file(file, purpose)
        self._ensure_bucket()
        object_path = contract_object_path(
            deal_id=deal_id,
            purpose=purpose,
            version=version,
            file_name=file.file_name,
        )
        content_type = normalized_content_type(file.content_type)
        try:
            self._client.storage.from_(CONTRACT_BUCKET).upload(
                path=object_path,
                file=file.content,
                file_options={
                    "content-type": content_type,
                    "cache-control": "3600",
                    "upsert": "false",
                },
            )
        except Exception as exc:
            raise ContractWorkspaceError("Could not store the contract file privately.") from exc
        return StoredContractFile(
            object_path=object_path,
            file_name=file.file_name,
            content_type=content_type,
            size_bytes=len(file.content),
        )

    def download(self, object_path: str) -> bytes:
        self._ensure_bucket()
        clean_path = str(object_path or "").strip()
        if not clean_path:
            raise ContractWorkspaceError("The contract file path is missing.")
        try:
            content = self._client.storage.from_(CONTRACT_BUCKET).download(clean_path)
        except Exception as exc:
            raise ContractWorkspaceError("Could not read the private contract file.") from exc
        if not isinstance(content, (bytes, bytearray)) or not content:
            raise ContractWorkspaceError("The private contract file was empty or unreadable.")
        return bytes(content)

    def signed_download_url(self, object_path: str, expires_in: int = 300) -> str:
        self._ensure_bucket()
        if expires_in < 60 or expires_in > 3600:
            raise ContractWorkspaceError("Private download links must expire between 1 minute and 1 hour.")
        try:
            result = self._client.storage.from_(CONTRACT_BUCKET).create_signed_url(object_path, expires_in)
        except Exception as exc:
            raise ContractWorkspaceError("Could not create a private contract download link.") from exc
        if isinstance(result, dict):
            return str(result.get("signedURL") or result.get("signedUrl") or "").strip()
        return str(getattr(result, "signed_url", "") or "").strip()
