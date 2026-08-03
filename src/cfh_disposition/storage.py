from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .models import BuyerProfile, OwnerFinanceProperty


class StorageError(RuntimeError):
    """Raised when persistent storage cannot complete an operation."""


class Storage(Protocol):
    mode: str

    def list_properties(self) -> list[OwnerFinanceProperty]: ...
    def save_property(self, item: OwnerFinanceProperty) -> None: ...
    def list_buyers(self) -> list[BuyerProfile]: ...
    def save_buyer(self, item: BuyerProfile) -> None: ...


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

    def list_buyers(self) -> list[BuyerProfile]:
        return [item.model_copy(deep=True) for item in self._buyers.values()]

    def save_buyer(self, item: BuyerProfile) -> None:
        self._buyers[str(item.buyer_id)] = item.model_copy(deep=True)


class SupabaseStorage:
    mode = "Supabase"

    def __init__(self, settings: SupabaseSettings, client: Any | None = None) -> None:
        if not settings.configured:
            raise ValueError("Supabase settings are incomplete")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise StorageError("Supabase client is not installed") from exc
            client = create_client(settings.url, settings.secret_key)
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


def build_storage(
    secrets: Mapping[str, Any],
    fallback_properties: list[OwnerFinanceProperty] | None = None,
    fallback_buyers: list[BuyerProfile] | None = None,
) -> Storage:
    settings = SupabaseSettings.from_mapping(secrets)
    if settings.configured:
        return SupabaseStorage(settings)
    return InMemoryStorage(fallback_properties, fallback_buyers)
