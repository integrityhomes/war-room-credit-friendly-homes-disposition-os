from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
from uuid import UUID, uuid4

from .models import BuyerProfile, OwnerFinanceProperty

PHOTO_BUCKET = "cfh-property-photos"
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PhotoUpload = tuple[str, bytes, str]


class StorageError(RuntimeError):
    """Raised when persistent storage cannot complete an operation."""


class Storage(Protocol):
    mode: str
    supports_photo_uploads: bool

    def list_properties(self) -> list[OwnerFinanceProperty]: ...
    def save_property(self, item: OwnerFinanceProperty) -> None: ...
    def delete_property(self, property_id: UUID) -> None: ...
    def upload_property_photos(self, property_id: UUID, files: list[PhotoUpload]) -> list[str]: ...
    def delete_property_photo(self, public_url: str) -> None: ...
    def list_buyers(self) -> list[BuyerProfile]: ...
    def save_buyer(self, item: BuyerProfile) -> None: ...
    def delete_buyer(self, buyer_id: UUID) -> None: ...


def validate_photo_upload(file_name: str, content: bytes, content_type: str) -> None:
    extension = Path(file_name).suffix.lower()
    if extension not in PHOTO_EXTENSIONS or content_type not in PHOTO_MIME_TYPES:
        raise StorageError("Only JPG, PNG, and WEBP property photos are allowed.")
    if not content:
        raise StorageError(f"{file_name} is empty.")
    if len(content) > PHOTO_MAX_BYTES:
        raise StorageError(f"{file_name} is larger than 10 MB.")


def _safe_photo_name(file_name: str) -> str:
    extension = Path(file_name).suffix.lower()
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(file_name).stem).strip("-")[:60]
    return f"{stem or 'property-photo'}-{uuid4().hex}{extension}"


def _public_photo_url(base_url: str, object_path: str) -> str:
    encoded_path = quote(object_path, safe="/")
    return f"{base_url.rstrip('/')}/storage/v1/object/public/{PHOTO_BUCKET}/{encoded_path}"


def _photo_path_from_url(base_url: str, public_url: str) -> str | None:
    prefix = f"{base_url.rstrip('/')}/storage/v1/object/public/{PHOTO_BUCKET}/"
    return public_url[len(prefix) :] if public_url.startswith(prefix) else None


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    secret_key: str

    @property
    def configured(self) -> bool:
        return bool(self.url and self.secret_key)

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> SupabaseSettings:
        secret = values.get("SUPABASE_SECRET_KEY") or values.get("SUPABASE_SERVICE_ROLE_KEY") or ""
        return cls(
            url=str(values.get("SUPABASE_URL", "")).strip(),
            secret_key=str(secret).strip(),
        )


class InMemoryStorage:
    mode = "Demo memory"
    supports_photo_uploads = False

    def __init__(
        self,
        properties: list[OwnerFinanceProperty] | None = None,
        buyers: list[BuyerProfile] | None = None,
    ) -> None:
        self._properties = {str(item.property_id): item.model_copy(deep=True) for item in properties or []}
        self._buyers = {str(item.buyer_id): item.model_copy(deep=True) for item in buyers or []}

    def list_properties(self) -> list[OwnerFinanceProperty]:
        return [item.model_copy(deep=True) for item in self._properties.values()]

    def save_property(self, item: OwnerFinanceProperty) -> None:
        self._properties[str(item.property_id)] = item.model_copy(deep=True)

    def delete_property(self, property_id: UUID) -> None:
        self._properties.pop(str(property_id), None)

    def upload_property_photos(self, property_id: UUID, files: list[PhotoUpload]) -> list[str]:
        raise StorageError("Connect Supabase before uploading property photos.")

    def delete_property_photo(self, public_url: str) -> None:
        raise StorageError("Connect Supabase before deleting uploaded photos.")

    def list_buyers(self) -> list[BuyerProfile]:
        return [item.model_copy(deep=True) for item in self._buyers.values()]

    def save_buyer(self, item: BuyerProfile) -> None:
        self._buyers[str(item.buyer_id)] = item.model_copy(deep=True)

    def delete_buyer(self, buyer_id: UUID) -> None:
        self._buyers.pop(str(buyer_id), None)


class SupabaseStorage:
    mode = "Supabase"
    supports_photo_uploads = True

    def __init__(self, settings: SupabaseSettings, client: Any | None = None) -> None:
        if not settings.configured:
            raise ValueError("Supabase settings are incomplete")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise StorageError("Supabase client is not installed") from exc
            client = create_client(settings.url, settings.secret_key)
        self._settings = settings
        self._client = client

    @staticmethod
    def _property_row(item: OwnerFinanceProperty) -> dict[str, Any]:
        return {
            "property_id": str(item.property_id),
            "status": item.status.value,
            "address": item.address,
            "city": item.city,
            "state": item.state,
            "zip_code": item.zip_code,
            "bedrooms": item.bedrooms,
            "monthly_payment": str(item.monthly_payment) if item.monthly_payment is not None else None,
            "down_payment": str(item.down_payment) if item.down_payment is not None else None,
            "payload": item.model_dump(mode="json"),
        }

    @staticmethod
    def _buyer_row(item: BuyerProfile) -> dict[str, Any]:
        return {
            "buyer_id": str(item.buyer_id),
            "first_name": item.first_name,
            "last_name": item.last_name,
            "email": item.email,
            "phone": item.phone,
            "do_not_contact": item.do_not_contact,
            "payload": item.model_dump(mode="json"),
        }

    def list_properties(self) -> list[OwnerFinanceProperty]:
        try:
            response = self._client.table("cfh_properties").select("payload").order("updated_at", desc=True).execute()
            return [OwnerFinanceProperty.model_validate(row["payload"]) for row in response.data or []]
        except Exception as exc:
            raise StorageError("Could not load properties from Supabase") from exc

    def save_property(self, item: OwnerFinanceProperty) -> None:
        try:
            self._client.table("cfh_properties").upsert(
                self._property_row(item),
                on_conflict="property_id",
            ).execute()
        except Exception as exc:
            raise StorageError("Could not save property to Supabase") from exc

    def upload_property_photos(self, property_id: UUID, files: list[PhotoUpload]) -> list[str]:
        uploaded_urls: list[str] = []
        bucket = self._client.storage.from_(PHOTO_BUCKET)
        for file_name, content, content_type in files:
            validate_photo_upload(file_name, content, content_type)
            object_path = f"{property_id}/{_safe_photo_name(file_name)}"
            try:
                bucket.upload(
                    path=object_path,
                    file=content,
                    file_options={
                        "content-type": content_type,
                        "cache-control": "3600",
                        "upsert": "false",
                    },
                )
            except Exception as exc:
                raise StorageError(
                    "Could not upload property photos. Confirm the cfh-property-photos bucket migration was run."
                ) from exc
            uploaded_urls.append(_public_photo_url(self._settings.url, object_path))
        return uploaded_urls

    def delete_property_photo(self, public_url: str) -> None:
        object_path = _photo_path_from_url(self._settings.url, public_url)
        if not object_path:
            return
        try:
            self._client.storage.from_(PHOTO_BUCKET).remove([object_path])
        except Exception as exc:
            raise StorageError("Could not delete the selected property photo from Supabase") from exc

    def _delete_property_photo_folder(self, property_id: UUID) -> None:
        try:
            bucket = self._client.storage.from_(PHOTO_BUCKET)
            response = bucket.list(str(property_id))
            paths = [f"{property_id}/{item['name']}" for item in response or [] if item.get("name")]
            if paths:
                bucket.remove(paths)
        except Exception:
            # Property deletion should still succeed if the bucket is missing or already empty.
            return

    def delete_property(self, property_id: UUID) -> None:
        try:
            self._delete_property_photo_folder(property_id)
            self._client.table("cfh_properties").delete().eq("property_id", str(property_id)).execute()
        except Exception as exc:
            raise StorageError("Could not delete property from Supabase") from exc

    def list_buyers(self) -> list[BuyerProfile]:
        try:
            response = self._client.table("cfh_buyers").select("payload").order("created_at", desc=True).execute()
            return [BuyerProfile.model_validate(row["payload"]) for row in response.data or []]
        except Exception as exc:
            raise StorageError("Could not load buyers from Supabase") from exc

    def save_buyer(self, item: BuyerProfile) -> None:
        try:
            self._client.table("cfh_buyers").upsert(
                self._buyer_row(item),
                on_conflict="buyer_id",
            ).execute()
        except Exception as exc:
            raise StorageError("Could not save buyer to Supabase") from exc

    def delete_buyer(self, buyer_id: UUID) -> None:
        try:
            self._client.table("cfh_buyers").delete().eq("buyer_id", str(buyer_id)).execute()
        except Exception as exc:
            raise StorageError("Could not delete buyer from Supabase") from exc


def build_storage(
    secrets: Mapping[str, Any],
    fallback_properties: list[OwnerFinanceProperty] | None = None,
    fallback_buyers: list[BuyerProfile] | None = None,
) -> Storage:
    settings = SupabaseSettings.from_mapping(secrets)
    if settings.configured:
        return SupabaseStorage(settings)
    return InMemoryStorage(fallback_properties, fallback_buyers)
