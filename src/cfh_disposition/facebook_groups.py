from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .storage import SupabaseSettings

FACEBOOK_GROUP_BUCKET = "cfh-facebook-group-posting"
FACEBOOK_GROUP_LEDGER_PATH = "facebook-groups/posting-ledger.json"
FACEBOOK_GROUP_TIMEZONE = "America/New_York"
FACEBOOK_GROUP_MAX_BYTES = 512 * 1024
DEFAULT_GROUP_COOLDOWN_DAYS = 7


class FacebookGroupError(RuntimeError):
    """Raised when the Facebook Group posting center cannot complete an operation."""


class FacebookGroupRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    group_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=2, max_length=160)
    group_url: str = Field(default="", max_length=500)
    cooldown_days: int = Field(default=DEFAULT_GROUP_COOLDOWN_DAYS, ge=1, le=90)
    active: bool = True
    notes: str = Field(default="", max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("group_url")
    @classmethod
    def validate_group_url(cls, value: str) -> str:
        if not value:
            return ""
        normalized = value if "://" in value else f"https://{value}"
        lowered = normalized.lower()
        if not lowered.startswith(("https://facebook.com/", "https://www.facebook.com/")):
            raise ValueError("Facebook Group URL must use facebook.com")
        return normalized.rstrip("/")


class FacebookGroupPostRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    post_id: str = Field(default_factory=lambda: str(uuid4()))
    property_id: str
    property_address: str
    group_id: str
    group_name: str
    posted_at: datetime
    posted_by: str = ""
    campaign: str = "owner_finance_homes"
    tracked_link: str = ""
    notes: str = Field(default="", max_length=1000)


class FacebookGroupLedger(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    groups: list[FacebookGroupRecord] = Field(default_factory=list)
    posts: list[FacebookGroupPostRecord] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FacebookGroupPostStatus:
    eligible: bool
    next_eligible_at: datetime | None
    wait_days: int
    last_post: FacebookGroupPostRecord | None
    message: str


def _business_timezone() -> ZoneInfo:
    return ZoneInfo(FACEBOOK_GROUP_TIMEZONE)


def business_now(now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(_business_timezone())


def active_groups(ledger: FacebookGroupLedger) -> list[FacebookGroupRecord]:
    return sorted(
        [group for group in ledger.groups if group.active],
        key=lambda group: group.name.lower(),
    )


def find_group(ledger: FacebookGroupLedger, group_id: str) -> FacebookGroupRecord | None:
    return next((group for group in ledger.groups if group.group_id == group_id), None)


def upsert_group(
    ledger: FacebookGroupLedger,
    *,
    name: str,
    group_url: str = "",
    cooldown_days: int = DEFAULT_GROUP_COOLDOWN_DAYS,
    notes: str = "",
    group_id: str | None = None,
    now: datetime | None = None,
) -> FacebookGroupLedger:
    timestamp = business_now(now)
    existing = find_group(ledger, group_id) if group_id else None
    if not existing:
        existing = next(
            (group for group in ledger.groups if group.name.strip().lower() == name.strip().lower()),
            None,
        )

    if existing:
        replacement = existing.model_copy(
            update={
                "name": name,
                "group_url": group_url,
                "cooldown_days": cooldown_days,
                "notes": notes,
                "active": True,
                "updated_at": timestamp.astimezone(UTC),
            }
        )
        groups = [replacement if group.group_id == existing.group_id else group for group in ledger.groups]
    else:
        replacement = FacebookGroupRecord(
            name=name,
            group_url=group_url,
            cooldown_days=cooldown_days,
            notes=notes,
            created_at=timestamp.astimezone(UTC),
            updated_at=timestamp.astimezone(UTC),
        )
        groups = [*ledger.groups, replacement]

    return ledger.model_copy(
        update={"groups": groups, "updated_at": timestamp.astimezone(UTC)}
    )


def deactivate_group(
    ledger: FacebookGroupLedger,
    *,
    group_id: str,
    now: datetime | None = None,
) -> FacebookGroupLedger:
    timestamp = business_now(now)
    found = False
    groups: list[FacebookGroupRecord] = []
    for group in ledger.groups:
        if group.group_id == group_id:
            found = True
            groups.append(
                group.model_copy(
                    update={"active": False, "updated_at": timestamp.astimezone(UTC)}
                )
            )
        else:
            groups.append(group)
    if not found:
        raise FacebookGroupError("The selected Facebook Group could not be found.")
    return ledger.model_copy(
        update={"groups": groups, "updated_at": timestamp.astimezone(UTC)}
    )


def latest_post_for_property_group(
    ledger: FacebookGroupLedger,
    *,
    property_id: UUID | str,
    group_id: str,
) -> FacebookGroupPostRecord | None:
    matches = [
        post
        for post in ledger.posts
        if post.property_id == str(property_id) and post.group_id == group_id
    ]
    return max(matches, key=lambda post: post.posted_at) if matches else None


def facebook_group_post_status(
    ledger: FacebookGroupLedger,
    *,
    property_id: UUID | str,
    group_id: str,
    now: datetime | None = None,
) -> FacebookGroupPostStatus:
    current = business_now(now)
    group = find_group(ledger, group_id)
    if not group:
        return FacebookGroupPostStatus(
            eligible=False,
            next_eligible_at=None,
            wait_days=0,
            last_post=None,
            message="The selected Facebook Group is not in the private group directory.",
        )
    if not group.active:
        return FacebookGroupPostStatus(
            eligible=False,
            next_eligible_at=None,
            wait_days=0,
            last_post=None,
            message="The selected Facebook Group is inactive. Reactivate it before posting.",
        )

    last_post = latest_post_for_property_group(
        ledger,
        property_id=property_id,
        group_id=group_id,
    )
    if not last_post:
        return FacebookGroupPostStatus(
            eligible=True,
            next_eligible_at=None,
            wait_days=0,
            last_post=None,
            message=f"This property has not been posted to {group.name}. It is ready for a manual post.",
        )

    posted_at = business_now(last_post.posted_at)
    next_eligible = posted_at + timedelta(days=group.cooldown_days)
    eligible = current >= next_eligible
    remaining_seconds = max((next_eligible - current).total_seconds(), 0)
    wait_days = int((remaining_seconds + 86399) // 86400) if remaining_seconds else 0
    if eligible:
        message = (
            f"The {group.cooldown_days}-day cooldown has passed. This property may be posted "
            f"to {group.name} again."
        )
    else:
        message = (
            f"Do not repost this property to {group.name} yet. The group cooldown ends "
            f"{next_eligible.strftime('%B %-d, %Y at %-I:%M %p ET')} "
            f"({wait_days} day{'s' if wait_days != 1 else ''} remaining)."
        )
    return FacebookGroupPostStatus(
        eligible=eligible,
        next_eligible_at=next_eligible,
        wait_days=wait_days,
        last_post=last_post,
        message=message,
    )


def record_facebook_group_post(
    ledger: FacebookGroupLedger,
    *,
    property_id: UUID | str,
    property_address: str,
    group_id: str,
    posted_by: str,
    campaign: str,
    tracked_link: str,
    notes: str = "",
    now: datetime | None = None,
) -> FacebookGroupLedger:
    timestamp = business_now(now)
    group = find_group(ledger, group_id)
    if not group:
        raise FacebookGroupError("The selected Facebook Group could not be found.")
    status = facebook_group_post_status(
        ledger,
        property_id=property_id,
        group_id=group_id,
        now=timestamp,
    )
    if not status.eligible:
        raise FacebookGroupError(status.message)

    record = FacebookGroupPostRecord(
        property_id=str(property_id),
        property_address=property_address,
        group_id=group.group_id,
        group_name=group.name,
        posted_at=timestamp.astimezone(UTC),
        posted_by=posted_by,
        campaign=campaign,
        tracked_link=tracked_link,
        notes=notes,
    )
    return ledger.model_copy(
        update={
            "posts": [*ledger.posts, record],
            "updated_at": timestamp.astimezone(UTC),
        }
    )


def group_directory_rows(ledger: FacebookGroupLedger) -> list[dict[str, str | int]]:
    rows: list[dict[str, str | int]] = []
    for group in sorted(ledger.groups, key=lambda item: item.name.lower()):
        rows.append(
            {
                "Group": group.name,
                "Active": "Yes" if group.active else "No",
                "Cooldown days": group.cooldown_days,
                "Facebook URL": group.group_url or "—",
                "Notes": group.notes or "—",
            }
        )
    return rows


def group_post_rows(
    ledger: FacebookGroupLedger,
    *,
    limit: int = 100,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for post in sorted(ledger.posts, key=lambda item: item.posted_at, reverse=True)[:limit]:
        rows.append(
            {
                "Property": post.property_address,
                "Facebook Group": post.group_name,
                "Posted": business_now(post.posted_at).strftime("%Y-%m-%d %I:%M %p ET"),
                "Posted by": post.posted_by or "—",
                "Campaign": post.campaign,
                "Notes": post.notes or "—",
            }
        )
    return rows


class FacebookGroupStore:
    """Private persistent Facebook Group directory and posting ledger."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise FacebookGroupError("Supabase is not configured for Facebook Group posting records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise FacebookGroupError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(FACEBOOK_GROUP_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    FACEBOOK_GROUP_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": FACEBOOK_GROUP_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise FacebookGroupError(
                    "Could not create the private Facebook Group posting bucket."
                ) from exc
        self._bucket_ready = True

    def load(self) -> FacebookGroupLedger:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(FACEBOOK_GROUP_BUCKET).download(
                FACEBOOK_GROUP_LEDGER_PATH
            )
        except Exception:
            return FacebookGroupLedger()
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return FacebookGroupLedger.model_validate(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise FacebookGroupError(
                "The saved Facebook Group directory and posting history could not be read."
            ) from exc

    def save(self, ledger: FacebookGroupLedger) -> None:
        self._ensure_bucket()
        payload = ledger.model_dump_json().encode("utf-8")
        if len(payload) > FACEBOOK_GROUP_MAX_BYTES:
            raise FacebookGroupError("The Facebook Group posting ledger is too large to save.")
        try:
            self._client.storage.from_(FACEBOOK_GROUP_BUCKET).upload(
                path=FACEBOOK_GROUP_LEDGER_PATH,
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise FacebookGroupError(
                "Could not save the Facebook Group directory and posting history."
            ) from exc
