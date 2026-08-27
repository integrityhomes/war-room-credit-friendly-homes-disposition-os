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
from .automatic_launch import (
    AutomationDispatchSettings,
    AutomationLaunchError,
    LaunchAction,
    automation_plan_rows,
    build_automatic_launch_payload,
    channel_copy_with_link,
    dispatch_automatic_launch,
    launch_action_for_channel,
)
from .buyer_handoff import enrich_launch_payload_with_buyer_audience
from .buyer_intent import BuyerIntentError, BuyerIntentStore, build_match_queue
from .channel_tracking import build_channel_links
from .channels import CHANNELS, CHANNELS_BY_KEY
from .dwelyx import tracking_app_base_url
from .launch_plan import build_launch_plan
from .marketplace_calendar import (
    MarketplaceCalendarError,
    MarketplaceCalendarStore,
    marketplace_month_status,
)
from .models import OwnerFinanceProperty
from .storage import StorageError, SupabaseSettings, build_storage

LAUNCH_BUCKET = "cfh-campaign-launches"
LAUNCH_MAX_BYTES = 128 * 1024


class LaunchStoreError(RuntimeError):
    """Raised when campaign launch records cannot be stored or loaded."""


class LaunchStatus(StrEnum):
    NOT_STARTED = "Not Started"
    READY = "Ready"
    POSTED = "Posted"
    SCHEDULED = "Scheduled"
    PAUSED = "Paused"
    FAILED = "Failed"


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


def new_launch_state(
    property_id: UUID | str,
    campaign: str,
    now: datetime | None = None,
) -> CampaignLaunchState:
    timestamp = now or datetime.now(UTC)
    return CampaignLaunchState(
        property_id=str(property_id),
        campaign=campaign_slug(campaign),
        updated_at=timestamp,
        channels={channel.key: ChannelLaunchRecord() for channel in CHANNELS},
    )


def ensure_all_channels(state: CampaignLaunchState) -> CampaignLaunchState:
    channels = {
        key: value.model_copy(deep=True)
        for key, value in state.channels.items()
        if key in CHANNELS_BY_KEY
    }
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
    channels = {
        key: value.model_copy(deep=True)
        for key, value in ensure_all_channels(state).channels.items()
    }
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


def _apply_marketplace_lock(
    state: CampaignLaunchState,
    *,
    blocked: bool,
    reason: str,
    updated_by: str,
    now: datetime,
) -> CampaignLaunchState:
    if not blocked:
        return state
    return set_channel_status(
        state,
        "marketplace",
        LaunchStatus.PAUSED,
        updated_by=updated_by,
        notes=reason,
        now=now,
    )


def _apply_payload_channel_blocks(
    state: CampaignLaunchState,
    payload: Mapping[str, Any],
    *,
    updated_by: str,
    now: datetime,
) -> CampaignLaunchState:
    updated = state
    for row in payload.get("channels", []):
        if not isinstance(row, Mapping) or not row.get("posting_blocked"):
            continue
        channel_key = str(row.get("channel_key", "")).strip()
        if channel_key not in CHANNELS_BY_KEY:
            continue
        reason = str(row.get("block_reason", "")).strip() or "Channel blocked by launch safety rules."
        updated = set_channel_status(
            updated,
            channel_key,
            LaunchStatus.PAUSED,
            updated_by=updated_by,
            notes=reason,
            now=now,
        )
    return updated


def _load_buyer_matches(
    secrets: Mapping[str, Any],
    property_record: OwnerFinanceProperty,
    dwelyx_url: str,
):
    try:
        buyers = build_storage(secrets).list_buyers()
        ledger = BuyerIntentStore(secrets).load()
        matches = build_match_queue(
            buyers,
            [property_record],
            ledger,
            dwelyx_url,
            minimum_score=35,
        )
        return matches, ""
    except (StorageError, BuyerIntentError) as exc:
        return [], str(exc)


def mark_automatic_launch_success(
    state: CampaignLaunchState,
    *,
    updated_by: str,
    now: datetime | None = None,
    marketplace_blocked: bool = False,
    marketplace_block_reason: str = "",
) -> CampaignLaunchState:
    timestamp = now or datetime.now(UTC)
    updated = approve_all_channels(state, approved_by=updated_by, now=timestamp)

    for channel in CHANNELS:
        if channel.key == "marketplace" and marketplace_blocked:
            status = LaunchStatus.PAUSED
            notes = marketplace_block_reason
        else:
            action = launch_action_for_channel(channel)
            if action == LaunchAction.INTERNAL_LIVE:
                status = LaunchStatus.POSTED
                notes = "Live automatically in the Credit Friendly Homes Disposition OS."
            elif action == LaunchAction.MANUAL_FINAL_POST:
                status = LaunchStatus.READY
                notes = (
                    "The complete package was delivered to the automation workflow. "
                    "This platform still requires a final human post."
                )
            else:
                status = LaunchStatus.SCHEDULED
                notes = "Sent to the connected automatic publishing workflow."
        updated = set_channel_status(
            updated,
            channel.key,
            status,
            updated_by=updated_by,
            notes=notes,
            now=timestamp,
        )
    return updated


def mark_automatic_launch_failure(
    state: CampaignLaunchState,
    *,
    updated_by: str,
    error_message: str,
    now: datetime | None = None,
    marketplace_blocked: bool = False,
    marketplace_block_reason: str = "",
) -> CampaignLaunchState:
    timestamp = now or datetime.now(UTC)
    updated = approve_all_channels(state, approved_by=updated_by, now=timestamp)

    for channel in CHANNELS:
        if channel.key == "marketplace" and marketplace_blocked:
            status = LaunchStatus.PAUSED
            notes = marketplace_block_reason
        else:
            action = launch_action_for_channel(channel)
            if action == LaunchAction.INTERNAL_LIVE:
                status = LaunchStatus.POSTED
                notes = "Live automatically in the Credit Friendly Homes Disposition OS."
            elif action == LaunchAction.MANUAL_FINAL_POST:
                status = LaunchStatus.READY
                notes = "Package is ready in this app, but automatic delivery failed."
            else:
                status = LaunchStatus.FAILED
                notes = error_message[:1000]
        updated = set_channel_status(
            updated,
            channel.key,
            status,
            updated_by=updated_by,
            notes=notes,
            now=timestamp,
        )
    return updated


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
                "Last updated (UTC)": (
                    record.updated_at.strftime("%Y-%m-%d %H:%M")
                    if record.updated_at
                    else "—"
                ),
                "Notes": record.notes or "—",
            }
        )
    return rows


def campaign_copy_for_channel(
    package: CampaignPackage,
    channel_key: str,
    tracked_link: str,
) -> str:
    return channel_copy_with_link(package, channel_key, tracked_link)


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
                raise LaunchStoreError(
                    "Could not automatically create the campaign-launch bucket."
                ) from exc
        self._bucket_ready = True

    def load(
        self,
        property_id: UUID | str,
        campaign: str,
    ) -> CampaignLaunchState | None:
        self._ensure_bucket()
        try:
            raw = self._client.storage.from_(LAUNCH_BUCKET).download(
                launch_object_path(property_id, campaign)
            )
        except Exception:
            return None
        try:
            payload = json.loads(
                raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            )
            return ensure_all_channels(
                CampaignLaunchState.model_validate(payload)
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise LaunchStoreError(
                "The saved campaign launch record could not be read."
            ) from exc

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


def _load_ui_state(
    store: CampaignLaunchStore | None,
    property_id: UUID | str,
    campaign: str,
) -> CampaignLaunchState:
    key = _state_key(property_id, campaign)
    cached = st.session_state.get(key)
    if cached:
        return ensure_all_channels(CampaignLaunchState.model_validate(cached))
    state = store.load(property_id, campaign) if store else None
    state = state or new_launch_state(property_id, campaign)
    st.session_state[key] = state.model_dump(mode="json")
    return state


def _save_ui_state(
    store: CampaignLaunchStore | None,
    state: CampaignLaunchState,
) -> None:
    if store:
        store.save(state)
    st.session_state[_state_key(state.property_id, state.campaign)] = state.model_dump(
        mode="json"
    )


def render_campaign_launch_center(
    properties: Sequence[OwnerFinanceProperty],
    secrets: Mapping[str, Any],
    dwelyx_url: str,
) -> None:
    channel_count = len(CHANNELS)
    st.subheader(f"{channel_count}-Channel Campaign Launch Center")
    st.caption(
        "Approve once, launch supported channels automatically, and track the few platforms "
        "that still require a final human post."
    )

    if not properties:
        st.info("Add and save a property before launching a campaign.")
        return

    options = {
        item.display_address or str(item.property_id): item
        for item in properties
    }
    selected_name = st.selectbox(
        "Choose property",
        list(options),
        key="launch_center_property",
    )
    selected = options[selected_name]
    plan = build_launch_plan(selected)
    if not plan.can_launch:
        st.error(
            "This property is not launch ready. Fix the blocking items in Record Manager first."
        )
        for error in plan.validation.errors:
            st.write(f"- {error}")
        return

    left, right = st.columns(2)
    campaign = left.text_input(
        "Campaign name",
        value="owner_finance_homes",
        key="launch_center_campaign",
    )
    operator = right.text_input(
        "Approved by",
        value="Sabrina",
        key="launch_center_operator",
    )
    campaign = campaign_slug(campaign)

    try:
        store: CampaignLaunchStore | None = CampaignLaunchStore(secrets)
        state = _load_ui_state(store, selected.property_id, campaign)
        st.success("Campaign status is saving permanently in Supabase.")
    except LaunchStoreError as exc:
        store = None
        state = _load_ui_state(None, selected.property_id, campaign)
        st.warning(f"Campaign status is temporary for this browser session: {exc}")

    try:
        marketplace_store = MarketplaceCalendarStore(secrets)
        marketplace_ledger = marketplace_store.load()
        marketplace_status = marketplace_month_status(
            marketplace_ledger,
            property_id=selected.property_id,
        )
        marketplace_blocked = (
            marketplace_status.blocked
            or marketplace_status.active_duplicate is not None
        )
        marketplace_block_reason = (
            marketplace_status.message if marketplace_blocked else ""
        )
        if marketplace_blocked:
            st.warning(
                "Facebook Marketplace is locked for this property: "
                f"{marketplace_status.message}"
            )
        else:
            st.info(
                f"Facebook Marketplace safety counter: {marketplace_status.used} of 5 used; "
                f"{marketplace_status.remaining} remaining."
            )
    except MarketplaceCalendarError as exc:
        marketplace_blocked = True
        marketplace_block_reason = (
            "Facebook Marketplace is locked because the monthly safety counter could not be read: "
            f"{exc}"
        )
        st.error(marketplace_block_reason)

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
    package = (
        CampaignPackage.model_validate(package_data)
        if package_data
        else build_fallback_campaign(selected, base_link)
    )
    campaign_source = (
        "AI campaign generated in Campaign Readiness"
        if package_data
        else "Safe campaign template"
    )
    st.caption(f"Copy source: {campaign_source}")

    buyer_matches, buyer_audience_error = _load_buyer_matches(
        secrets,
        selected,
        dwelyx_url,
    )
    email_ready = sum(1 for match in buyer_matches if match.email_allowed and match.email)
    sms_ready = sum(1 for match in buyer_matches if match.sms_allowed and match.phone)
    audience_metrics = st.columns(3)
    audience_metrics[0].metric("Consent-ready matches", len(buyer_matches))
    audience_metrics[1].metric("Email recipients", email_ready)
    audience_metrics[2].metric("SMS recipients", sms_ready)
    if buyer_audience_error:
        st.warning(
            "Buyer audience could not be loaded, so email and SMS will be safety-blocked for this launch. "
            f"Reason: {buyer_audience_error}"
        )
    elif not buyer_matches:
        st.info(
            "No consent-ready buyer matches were found for this property. Email and SMS will not send until matching buyers exist."
        )
    else:
        st.success(
            "Email and SMS will be handed to REI BlackBook one buyer at a time using the saved, consent-checked recipient information."
        )

    if selected.photo_urls:
        st.image(str(selected.photo_urls[0]), width=420)

    st.write("### Automatic Launch Engine")
    st.info(
        "No property is published or synced to Dwelyx. Facebook Marketplace has no direct link. "
        "Facebook Groups and supported non-Marketplace channels may use the tracked Dwelyx buyer link."
    )
    automation_settings = AutomationDispatchSettings.from_mapping(secrets)
    if automation_settings.configured:
        st.success("The automatic publishing workflow is connected.")
    else:
        st.warning(
            "Automatic external publishing is not connected yet. Add AUTOMATION_WEBHOOK_URL "
            "in Streamlit Secrets after creating the Make.com publishing workflow."
        )

    with st.expander(f"See what happens on all {channel_count} channels"):
        st.dataframe(
            pd.DataFrame(automation_plan_rows()),
            use_container_width=True,
            hide_index=True,
            height=max(420, channel_count * 35 + 45),
        )

    launch_disabled = not automation_settings.configured
    if st.button(
        "Approve & Launch Supported Channels",
        type="primary",
        use_container_width=True,
        disabled=launch_disabled,
    ):
        approved_at = datetime.now(UTC)
        payload = build_automatic_launch_payload(
            selected,
            package,
            links_by_key,
            campaign=campaign,
            approved_by=operator,
            approved_at=approved_at,
            marketplace_blocked=marketplace_blocked,
            marketplace_block_reason=marketplace_block_reason,
        )
        payload = enrich_launch_payload_with_buyer_audience(payload, buyer_matches)
        try:
            with st.spinner(
                "Sending the approved campaign to the publishing workflow..."
            ):
                receipt = dispatch_automatic_launch(
                    payload,
                    automation_settings,
                )
            state = mark_automatic_launch_success(
                state,
                updated_by=operator,
                now=receipt.sent_at,
                marketplace_blocked=marketplace_blocked,
                marketplace_block_reason=marketplace_block_reason,
            )
            state = _apply_payload_channel_blocks(
                state,
                payload,
                updated_by=operator,
                now=receipt.sent_at,
            )
            _save_ui_state(store, state)
            st.success(
                "Campaign accepted by the automatic publishing workflow. Restricted or safety-blocked "
                "channels remain paused or ready instead of being falsely marked sent."
            )
        except (AutomationLaunchError, LaunchStoreError) as exc:
            state = mark_automatic_launch_failure(
                state,
                updated_by=operator,
                error_message=str(exc),
                now=approved_at,
                marketplace_blocked=marketplace_blocked,
                marketplace_block_reason=marketplace_block_reason,
            )
            state = _apply_payload_channel_blocks(
                state,
                payload,
                updated_by=operator,
                now=approved_at,
            )
            try:
                _save_ui_state(store, state)
            except LaunchStoreError:
                pass
            st.error(str(exc))

    approve_left, approve_right = st.columns([1, 2])
    if approve_left.button(
        "Approve Only — Do Not Launch",
        use_container_width=True,
    ):
        approval_time = datetime.now(UTC)
        state = approve_all_channels(
            state,
            approved_by=operator,
            now=approval_time,
        )
        state = _apply_marketplace_lock(
            state,
            blocked=marketplace_blocked,
            reason=marketplace_block_reason,
            updated_by=operator,
            now=approval_time,
        )
        try:
            _save_ui_state(store, state)
            st.success(
                "All available channels are approved and marked Ready, but nothing was launched."
            )
        except LaunchStoreError as exc:
            st.error(str(exc))
    if state.approved_at:
        approve_right.info(
            f"Approved by {state.approved_by or 'team'} on "
            f"{state.approved_at.strftime('%Y-%m-%d %H:%M UTC')}."
        )
    else:
        approve_right.info("Review the property facts and campaign copy before approval.")

    st.write("### Restricted channel or troubleshooting review")
    st.caption(
        "Use this section for Facebook Marketplace, Facebook Groups, classifieds, Nextdoor, "
        "or troubleshooting an automatic channel."
    )
    selected_channel_name = st.selectbox(
        "Choose marketing channel",
        [channel.name for channel in CHANNELS],
        key="launch_center_channel",
    )
    channel = next(
        item for item in CHANNELS if item.name == selected_channel_name
    )
    tracked_link = links_by_key[channel.key]["Tracked Dwelyx link"]
    marketplace_channel_locked = (
        channel.key == "marketplace" and marketplace_blocked
    )

    if marketplace_channel_locked:
        st.error(marketplace_block_reason)
        st.text_area(
            "Marketplace package locked",
            value=marketplace_block_reason,
            height=150,
            disabled=True,
        )
    else:
        copy_text = campaign_copy_for_channel(
            package,
            channel.key,
            tracked_link,
        )
        if channel.key == "marketplace":
            st.info(
                "Facebook Marketplace copy intentionally contains no website or Dwelyx link. "
                "Buyers are instructed to message through Marketplace."
            )
        else:
            st.text_input(
                "Tracked Dwelyx buyer-account link for this channel",
                value=tracked_link,
                key=f"launch_link_{channel.key}",
            )
            st.link_button("Test This Channel Link", tracked_link)
        st.text_area(
            "Complete marketing package",
            value=copy_text,
            height=320,
            key=f"launch_copy_{channel.key}",
        )
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
            "Posting location, group name, ad ID, refresh date, error, or notes",
            value=current.notes,
            height=100,
            key=f"launch_notes_{channel.key}",
        )
        if st.button("Save This Channel Status", type="primary"):
            state = set_channel_status(
                state,
                channel.key,
                status,
                updated_by=operator,
                notes=notes,
            )
            try:
                _save_ui_state(store, state)
                st.success(f"{channel.name} is saved as {status.value}.")
            except LaunchStoreError as exc:
                st.error(str(exc))

    st.write("### Complete campaign status")
    table = pd.DataFrame(launch_rows(state))
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        height=max(420, channel_count * 35 + 45),
    )
    st.download_button(
        "Download Campaign Launch Sheet (CSV)",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name=f"cfh_campaign_launch_{campaign}.csv",
        mime="text/csv",
    )
    st.markdown(
        f"[Open the {channel_count}-Channel Marketing Analytics dashboard](?analytics=1)"
    )
    st.markdown(
        f"[Open the {channel_count}-Channel Link Center](?channel_center=1)"
    )
