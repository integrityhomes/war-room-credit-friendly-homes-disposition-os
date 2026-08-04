from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import pandas as pd
import streamlit as st
from pydantic import BaseModel, ConfigDict, Field

from .ai_campaign import CampaignPackage, build_fallback_campaign
from .channel_tracking import build_channel_links
from .channels import CHANNELS, CHANNELS_BY_KEY
from .dwelyx import tracking_app_base_url
from .launch_plan import build_launch_plan
from .models import OwnerFinanceProperty
from .storage import SupabaseSettings

LAUNCH_BUCKET = "cfh-campaign-launches"
LAUNCH_MAX_BYTES = 128 * 1024
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")


class LaunchStoreError(RuntimeError):
    """Raised when campaign launch records cannot be stored or loaded."""


class LaunchStatus(StrEnum):
    NOT_STARTED = "Not Started"
    READY = "Ready"
    POSTED = "Posted"
    SCHEDULED = "Scheduled"
    PAUSED = "Paused"


class ChannelLaunchRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: LaunchStatus = LaunchStatus.NOT_STARTED
    updated_at: datetime | None = None
    updated_by: str = ""
    notes: str = Field(default="", max_length=1000)


class CampaignLaunchState(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    property_id: str
    campaign: str
    approved_at: datetime | None = None
    approved_by: str = ""
    updated_at: datetime
    channels: dict[str, ChannelLaunchRecord]


def campaign_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug[:80] or "owner_finance_homes"


def launch_object_path(property_id: UUID | str, campaign: str) -> str:
    return f"launches/{property_id}/{campaign_slug(campaign)}.json"


def new_launch_state(property_id: UUID | str, campaign: str, now: datetime | None = None) -> CampaignLaunchState:
    timestamp = now or datetime.now(UTC)
    return CampaignLaunchState(
        property_id=str(property_id),
        campaign=campaign_slug(campaign),
        updated_at=timestamp,
        channels={channel.key: ChannelLaunchRecord() for channel in CHANNELS},
    )


def ensure_all_channels(state: CampaignLaunchState) -> CampaignLaunchState:
    channels = {key: value.model_copy(deep=True) for key, value in state.channels.items() if key in CHANNELS_BY_KEY}
    for channel in CHANNELS:
        channels.setdefault(channel.key, ChannelLaunchRecord())
    return state.model_copy(update={"channels": channels})


def set_channel_status(
    state: CampaignLaunchState,
    channel_key: str,
    status: LaunchStatus,
    *,
    updated_by: str = "",
    notes: str = "",
    now: datetime | None = None,
) -> CampaignLaunchState:
    if channel_key not in CHANNELS_BY_KEY:
        raise ValueError(f"Unknown marketing channel: {channel_key}")
    timestamp = now or datetime.now(UTC)
    channels = {key: value.model_copy(deep=True) for key, value in ensure_all_channels(state).channels.items()}
    channels[channel_key] = ChannelLaunchRecord(
        status=status,
        updated_at=timestamp,
        updated_by=updated_by,
        notes=notes,
    )
    return state.model_copy(update={"channels": channels, "updated_at": timestamp})


def approve_all_channels(
    state: CampaignLaunchState,
    *,
    approved_by: str = "",
    now: datetime | None = None,
) -> CampaignLaunchState:
    timestamp = now or datetime.now(UTC)
    channels = {
        channel.key: ChannelLaunchRecord(
            status=LaunchStatus.READY,
            updated_at=timestamp,
            updated_by=approved_by,
            notes=state.channels.get(channel.key, ChannelLaunchRecord()).notes,
        )
        for channel in CHANNELS
    }
    return state.model_copy(
        update={
            "channels": channels,
            "approved_at": timestamp,
            "approved_by": approved_by,
            "updated_at": timestamp,
        }
    )


def launch_rows(state: CampaignLaunchState) -> list[dict[str, str]]:
    state = ensure_all_channels(state)
    rows: list[dict[str, str]] = []
    for channel in CHANNELS:
        record = state.channels[channel.key]
        rows.append(
            {
                "Channel": channel.name,
                "Mode": channel.mode.value,
                "Status": record.status.value,
                "Updated by": record.updated_by or "—",
                "Last updated (UTC)": record.updated_at.strftime("%Y-%m-%d %H:%M") if record.updated_at else "—",
                "Notes": record.notes or "—",
            }
        )
    return rows


def _copy_source(package: CampaignPackage, channel_key: str) -> str:
    mapping = {
        "property_page": package.short_description,
        "blog": package.short_description,
        "market_seo": package.short_description,
        "email": f"Subject: {package.email_subject}\n\n{package.email_body}",
        "sms": package.sms_message,
        "reactivation": package.sms_message,
        "marketplace": package.marketplace_description,
        "facebook_groups": package.facebook_group_post,
        "meta_ads": f"{package.headline}\n\n{package.short_description}",
        "google_ads": f"{package.headline}\n\n{package.short_description}",
        "instagram": package.social_caption,
        "tiktok": package.video_script,
        "youtube": package.video_script,
        "classifieds": package.classified_ad,
    }
    try:
        return mapping[channel_key]
    except KeyError as exc:
        raise ValueError(f"Unknown marketing channel: {channel_key}") from exc


def campaign_copy_for_channel(package: CampaignPackage, channel_key: str, tracked_link: str) -> str:
    source = _copy_source(package, channel_key).strip()
    matches = URL_PATTERN.findall(source)
    if matches:
        source = URL_PATTERN.sub(tracked_link, source)
    elif tracked_link not in source:
        source = f"{source}\n\nBrowse on Dwelyx: {tracked_link}"
    return source


class CampaignLaunchStore:
    """Private no-SQL campaign workflow storage backed by Supabase Storage."""

    def __init__(self, values: Mapping[str, Any], client: Any | None = None) -> None:
        settings = SupabaseSettings.from_mapping(values)
        if not settings.configured:
            raise LaunchStoreError("Supabase is not configured for campaign launch records.")
        if client is None:
            try:
                from supabase import create_client
            except ImportError as exc:
                raise LaunchStoreError("Supabase client is not installed.") from exc
            client = create_client(settings.url, settings.secret_key)
        self._client = client
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.storage.get_bucket(LAUNCH_BUCKET)
        except Exception:
            try:
                self._client.storage.create_bucket(
                    LAUNCH_BUCKET,
                    options={
                        "public": False,
                        "allowed_mime_types": ["application/json"],
                        "file_size_limit": LAUNCH_MAX_BYTES,
                    },
                )
            except Exception as exc:
                raise LaunchStoreError("Could not automatically create the campaign-launch bucket.") from exc
        self._bucket_ready = True

    def load(self, property_id: UUID | str, campaign: str) -> CampaignLaunchState | None:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(LAUNCH_BUCKET).download(launch_object_path(property_id, campaign))
        except Exception:
            return None
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
            return ensure_all_channels(CampaignLaunchState.model_validate(payload))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise LaunchStoreError("The saved campaign launch record could not be read.") from exc

    def save(self, state: CampaignLaunchState) -> None:
        self._ensure_bucket()
        payload = state.model_dump_json().encode("utf-8")
        if len(payload) > LAUNCH_MAX_BYTES:
            raise LaunchStoreError("The campaign launch record is too large to save.")
        try:
            self._client.storage.from_(LAUNCH_BUCKET).upload(
                path=launch_object_path(state.property_id, state.campaign),
                file=payload,
                file_options={
                    "content-type": "application/json",
                    "cache-control": "0",
                    "upsert": "true",
                },
            )
        except Exception as exc:
            raise LaunchStoreError("Could not save the campaign launch record.") from exc


def _state_key(property_id: UUID | str, campaign: str) -> str:
    return f"campaign_launch::{property_id}::{campaign_slug(campaign)}"


def _load_ui_state(store: CampaignLaunchStore | None, property_id: UUID | str, campaign: str) -> CampaignLaunchState:
    key = _state_key(property_id, campaign)
    cached = st.session_state.get(key)
    if cached:
        return ensure_all_channels(CampaignLaunchState.model_validate(cached))
    state = store.load(property_id, campaign) if store else None
    state = state or new_launch_state(property_id, campaign)
    st.session_state[key] = state.model_dump(mode="json")
    return state


def _save_ui_state(store: CampaignLaunchStore | None, state: CampaignLaunchState) -> None:
    if store:
        store.save(state)
    st.session_state[_state_key(state.property_id, state.campaign)] = state.model_dump(mode="json")


def render_campaign_launch_center(
    properties: Sequence[OwnerFinanceProperty],
    secrets: Mapping[str, Any],
    dwelyx_url: str,
) -> None:
    st.subheader("14-Channel Campaign Launch Center")
    st.caption("Approve the campaign, copy the correct tracked package, and record exactly where each property was marketed.")

    if not properties:
        st.info("Add and save a property before launching a campaign.")
        return

    options = {item.display_address or str(item.property_id): item for item in properties}
    selected_name = st.selectbox("Choose property", list(options), key="launch_center_property")
    selected = options[selected_name]
    plan = build_launch_plan(selected)
    if not plan.can_launch:
        st.error("This property is not launch ready. Fix the blocking items in Record Manager first.")
        for error in plan.validation.errors:
            st.write(f"- {error}")
        return

    left, right = st.columns(2)
    campaign = left.text_input("Campaign name", value="owner_finance_homes", key="launch_center_campaign")
    operator = right.text_input("Posted or approved by", value="Sabrina", key="launch_center_operator")
    campaign = campaign_slug(campaign)

    try:
        store: CampaignLaunchStore | None = CampaignLaunchStore(secrets)
        state = _load_ui_state(store, selected.property_id, campaign)
        st.success("Campaign status is saving permanently in Supabase.")
    except LaunchStoreError as exc:
        store = None
        state = _load_ui_state(None, selected.property_id, campaign)
        st.warning(f"Campaign status is temporary for this browser session: {exc}")

    links = build_channel_links(
        dwelyx_url,
        campaign=campaign,
        property_id=selected.property_id,
        tracking_base_url=tracking_app_base_url(secrets),
    )
    links_by_key = {row["Channel key"]: row for row in links}
    base_link = links_by_key["property_page"]["Tracked Dwelyx link"]

    campaign_key = f"campaign_package_{selected.property_id}"
    package_data = st.session_state.get(campaign_key)
    package = CampaignPackage.model_validate(package_data) if package_data else build_fallback_campaign(selected, base_link)
    campaign_source = "AI campaign generated in Campaign Readiness" if package_data else "Safe campaign template"
    st.caption(f"Copy source: {campaign_source}")

    if selected.photo_urls:
        st.image(str(selected.photo_urls[0]), width=420)

    approve_left, approve_right = st.columns([1, 2])
    if approve_left.button("Approve All 14 Channels as Ready", type="primary", use_container_width=True):
        state = approve_all_channels(state, approved_by=operator)
        try:
            _save_ui_state(store, state)
            st.success("All 14 channels are approved and marked Ready.")
        except LaunchStoreError as exc:
            st.error(str(exc))
    if state.approved_at:
        approve_right.info(
            f"Approved by {state.approved_by or 'team'} on {state.approved_at.strftime('%Y-%m-%d %H:%M UTC')}."
        )
    else:
        approve_right.info("Approve the campaign after the property facts and generated copy have been reviewed.")

    st.write("### Work one channel")
    selected_channel_name = st.selectbox("Choose marketing channel", [channel.name for channel in CHANNELS], key="launch_center_channel")
    channel = next(item for item in CHANNELS if item.name == selected_channel_name)
    tracked_link = links_by_key[channel.key]["Tracked Dwelyx link"]
    copy_text = campaign_copy_for_channel(package, channel.key, tracked_link)

    st.text_input("Tracked Dwelyx link for this channel", value=tracked_link, key=f"launch_link_{channel.key}")
    st.text_area("Copy this complete marketing package", value=copy_text, height=320, key=f"launch_copy_{channel.key}")
    st.link_button("Test This Channel Link", tracked_link)
    st.caption(f"Posting mode: {channel.mode.value}. {channel.purpose}")

    current = ensure_all_channels(state).channels[channel.key]
    status_values = list(LaunchStatus)
    status = st.selectbox(
        "Channel status",
        status_values,
        index=status_values.index(current.status),
        format_func=lambda value: value.value,
        key=f"launch_status_{channel.key}",
    )
    notes = st.text_area(
        "Posting location, group name, ad ID, refresh date, or notes",
        value=current.notes,
        height=100,
        key=f"launch_notes_{channel.key}",
    )
    if st.button("Save This Channel Status", type="primary"):
        state = set_channel_status(state, channel.key, status, updated_by=operator, notes=notes)
        try:
            _save_ui_state(store, state)
            st.success(f"{channel.name} is saved as {status.value}.")
        except LaunchStoreError as exc:
            st.error(str(exc))

    st.write("### Complete campaign status")
    table = pd.DataFrame(launch_rows(state))
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.download_button(
        "Download Campaign Launch Sheet (CSV)",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name=f"cfh_campaign_launch_{campaign}.csv",
        mime="text/csv",
    )
    st.markdown("[Open the 14-Channel Marketing Analytics dashboard](?analytics=1)")
    st.markdown("[Open the 14-Channel Link Center](?channel_center=1)")
