from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .storage import SupabaseSettings

MARKETPLACE_BUCKET = "cfh-marketplace-ledger"
MARKETPLACE_LEDGER_PATH = "marketplace/listing-ledger.json"
MARKETPLACE_MONTHLY_LIMIT = 5
MARKETPLACE_TIMEZONE = "America/New_York"
MARKETPLACE_MAX_BYTES = 256 * 1024


class MarketplaceCalendarError(RuntimeError):
    """Raised when the Marketplace safety ledger cannot be read or updated."""


class MarketplaceListingType(StrEnum):
    FOR_SALE = "For Sale"
    FOR_RENT = "For Rent"


class MarketplaceListingRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    listing_id: str = Field(default_factory=lambda: str(uuid4()))
    property_id: str
    address: str
    listing_type: MarketplaceListingType
    created_at: datetime
    created_by: str = ""
    notes: str = Field(default="", max_length=1000)
    active: bool = True
    closed_at: datetime | None = None
    closed_by: str = ""


class MarketplaceLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    listings: list[MarketplaceListingRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MarketplaceMonthStatus:
    used: int
    remaining: int
    blocked: bool
    reset_at: datetime
    wait_days: int
    required_listing_type: MarketplaceListingType
    active_duplicate: MarketplaceListingRecord | None
    message: str


def _business_timezone() -> ZoneInfo:
    return ZoneInfo(MARKETPLACE_TIMEZONE)


def business_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(_business_timezone())


def next_reset_at(now: datetime | None = None) -> datetime:
    current = business_now(now)
    if current.month == 12:
        year, month = current.year + 1, 1
    else:
        year, month = current.year, current.month + 1
    return datetime(year, month, 1, 0, 0, tzinfo=_business_timezone())


def current_month_listings(
    ledger: MarketplaceLedger,
    now: datetime | None = None,
) -> list[MarketplaceListingRecord]:
    current = business_now(now)
    rows: list[MarketplaceListingRecord] = []
    for listing in ledger.listings:
        created = business_now(listing.created_at)
        if created.year == current.year and created.month == current.month:
            rows.append(listing)
    return sorted(rows, key=lambda item: item.created_at)


def active_listing_for_property(
    ledger: MarketplaceLedger,
    property_id: UUID | str,
) -> MarketplaceListingRecord | None:
    wanted = str(property_id)
    active = [item for item in ledger.listings if item.property_id == wanted and item.active]
    return max(active, key=lambda item: item.created_at) if active else None


def marketplace_month_status(
    ledger: MarketplaceLedger,
    *,
    property_id: UUID | str | None = None,
    now: datetime | None = None,
    monthly_limit: int = MARKETPLACE_MONTHLY_LIMIT,
) -> MarketplaceMonthStatus:
    current = business_now(now)
    reset_at = next_reset_at(current)
    used = len(current_month_listings(ledger, current))
    remaining = max(monthly_limit - used, 0)
    blocked = used >= monthly_limit
    wait_days = max((reset_at.date() - current.date()).days, 0)
    duplicate = active_listing_for_property(ledger, property_id) if property_id else None
    required = MarketplaceListingType.FOR_SALE

    if blocked:
        message = (
            f"Facebook Marketplace monthly limit reached: {used} of {monthly_limit} Homes for Sale or Rent "
            f"listings have been created. Deleted listings still count. New Marketplace ad creation unlocks "
            f"{reset_at.strftime('%B %-d, %Y')} in {wait_days} day{'s' if wait_days != 1 else ''}."
        )
    elif duplicate:
        message = (
            "This property already has an active Facebook Marketplace listing. Do not create another listing "
            "under either For Sale or For Rent. Edit, renew, or close the existing listing first."
        )
    else:
        message = (
            f"Marketplace has {remaining} of {monthly_limit} Homes for Sale or Rent listing slots remaining "
            "this month. Owner-finance homes must be posted under For Sale because they are sales, not rentals."
        )

    return MarketplaceMonthStatus(
        used=used,
        remaining=remaining,
        blocked=blocked,
        reset_at=reset_at,
        wait_days=wait_days,
        required_listing_type=required,
        active_duplicate=duplicate,
        message=message,
    )


def record_marketplace_listing(
    ledger: MarketplaceLedger,
    *,
    property_id: UUID | str,
    address: str,
    listing_type: MarketplaceListingType,
    created_by: str,
    notes: str = "",
    now: datetime | None = None,
    monthly_limit: int = MARKETPLACE_MONTHLY_LIMIT,
) -> MarketplaceLedger:
    timestamp = business_now(now)
    status = marketplace_month_status(
        ledger,
        property_id=property_id,
        now=timestamp,
        monthly_limit=monthly_limit,
    )
    if status.blocked:
        raise MarketplaceCalendarError(status.message)
    if status.active_duplicate:
        raise MarketplaceCalendarError(status.message)
    if listing_type != MarketplaceListingType.FOR_SALE:
        raise MarketplaceCalendarError(
            "Owner-finance properties must be listed under For Sale. Do not use For Rent unless the property "
            "is genuinely being offered under a rental lease with true rental terms."
        )

    record = MarketplaceListingRecord(
        property_id=str(property_id),
        address=address,
        listing_type=listing_type,
        created_at=timestamp,
        created_by=created_by,
        notes=notes,
    )
    return ledger.model_copy(
        update={
            "listings": [*ledger.listings, record],
            "updated_at": timestamp.astimezone(UTC),
        }
    )


def close_marketplace_listing(
    ledger: MarketplaceLedger,
    *,
    listing_id: str,
    closed_by: str,
    now: datetime | None = None,
) -> MarketplaceLedger:
    timestamp = business_now(now)
    found = False
    updated: list[MarketplaceListingRecord] = []
    for item in ledger.listings:
        if item.listing_id == listing_id and item.active:
            found = True
            updated.append(
                item.model_copy(
                    update={
                        "active": False,
                        "closed_at": timestamp,
                        "closed_by": closed_by,
                    }
                )
            )
        else:
            updated.append(item)
    if not found:
        raise MarketplaceCalendarError("The active Marketplace listing could not be found.")
    return ledger.model_copy(
        update={"listings": updated, "updated_at": timestamp.astimezone(UTC)}
    )


def marketplace_ledger_rows(
    ledger: MarketplaceLedger,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in current_month_listings(ledger, now):
        rows.append(
            {
                "Property": item.address,
                "Category": item.listing_type.value,
                "Created": business_now(item.created_at).strftime("%Y-%m-%d %I:%M %p ET"),
                "Created by": item.created_by or "—",
                "Active": "Yes" if item.active else "No",
                "Notes": item.notes or "—",
            }
        )
    return rows


class MarketplaceCalendarStore:
    """Private persistent Marketplace listing ledger backed by Supabase Storage."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise MarketplaceCalendarError("Supabase is not configured for the Marketplace monthly counter.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise MarketplaceCalendarError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(MARKETPLACE_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    MARKETPLACE_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": MARKETPLACE_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise MarketplaceCalendarError(
                    "Could not create the private Marketplace monthly-counter bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> MarketplaceLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(MARKETPLACE_BUCKET).download(MARKETPLACE_LEDGER_PATH)
        except Exception:
            return MarketplaceLedger()
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return MarketplaceLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MarketplaceCalendarError("The Marketplace monthly counter could not be read.") from exc

    def save(self, ledger: MarketplaceLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > MARKETPLACE_MAX_BYTES:
            raise MarketplaceCalendarError("The Marketplace listing ledger is too large to save.")
        try:
            self._client.storage.from_(MARKETPLACE_BUCKET).upload(
                path=MARKETPLACE_LEDGER_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise MarketplaceCalendarError("Could not save the Marketplace monthly counter.") from exc
