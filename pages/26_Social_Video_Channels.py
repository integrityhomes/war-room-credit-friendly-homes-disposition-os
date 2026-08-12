from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.social_video_channels import (
    SocialVideoPackageError,
    build_social_video_package,
)
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Instagram, TikTok & YouTube",
    page_icon="🎬",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Instagram, TikTok & YouTube")
    st.caption("Private internal access")
    with st.form("social_video_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


def property_label(item) -> str:
    return item.display_address or str(item.property_id)


require_password()
st.title("Instagram, TikTok & YouTube")
st.caption(
    "Build one fact-safe short-form property package, then use the channel-specific tracked Dwelyx link for Instagram, TikTok, or YouTube Shorts."
)
st.info(
    "This page prepares content and attribution. Final publishing stays approval-controlled so the team can review the property facts and creative before posting."
)

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("Add a property before creating social video packages.")
    st.stop()

property_options = {property_label(item): item for item in properties}
selected_label = st.selectbox("Property", list(property_options))
selected = property_options[selected_label]

campaign = st.text_input(
    "Campaign name",
    value=f"social_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
).strip()
if not campaign:
    st.warning("Enter a campaign name.")
    st.stop()

links = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
links_by_key = {row["Channel key"]: row["Tracked Dwelyx link"] for row in links}

channel_keys = ("instagram", "tiktok", "youtube")
channel_tabs = st.tabs([CHANNELS_BY_KEY[key].name for key in channel_keys])

for tab, key in zip(channel_tabs, channel_keys, strict=True):
    channel = CHANNELS_BY_KEY[key]
    with tab:
        try:
            package = build_social_video_package(
                selected,
                channel_key=key,
                channel_name=channel.name,
                tracked_link=links_by_key[key],
            )
        except SocialVideoPackageError as exc:
            st.error(f"Fact guard blocked this package: {exc}")
            continue

        metrics = st.columns(4)
        metrics[0].metric("Channel", channel.name)
        metrics[1].metric("Mode", channel.mode.value)
        metrics[2].metric("Campaign", campaign)
        metrics[3].metric("Publish", "Approval Required")

        st.write("### Hook")
        st.code(package.hook, language=None)

        st.write("### Caption / Post Copy")
        st.text_area(
            f"{channel.name} copy",
            value=package.caption,
            height=260,
            key=f"caption_{key}",
        )

        st.write("### 30–45 second video script")
        st.text_area(
            f"{channel.name} script",
            value=package.short_script,
            height=220,
            key=f"script_{key}",
        )

        st.write("### Shot list")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Shot": index, "Capture": item}
                    for index, item in enumerate(package.shot_list, start=1)
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        st.write("### Tracked Dwelyx link")
        st.code(package.tracked_link, language=None)
        st.caption(
            f"Use this exact link with the {channel.name} content so registrations, applications, showings, contracts, and filled homes can be attributed back to this channel and campaign."
        )

st.warning(
    "Before posting: verify the property is still available, confirm all displayed terms, "
    "review the photos/video, and approve the final creative. Do not promise buyer approval "
    "or change verified property facts in the copy."
)
