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
    page_title="Instagram TikTok YouTube Shorts",
    page_icon="🎬",
    layout="wide",
)

SOCIAL_CHANNEL_KEYS = ("instagram", "tiktok", "youtube")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Instagram + TikTok + YouTube Shorts")
    st.caption("Private internal access")
    with st.form("social_short_form_login"):
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


require_password()
st.title("Instagram Reels & Posts + TikTok + YouTube Shorts")
st.caption(
    "Build three short-form property marketing packages at once, each with its own tracked Dwelyx attribution."
)
st.info(
    "This creates copy, scripts, shot plans, and tracked links. It does not alter the property's appearance, invent facts, or automatically publish without approval."
)

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("Add and save a property before creating social packages.")
    st.stop()

property_options = {
    item.display_address or str(item.property_id): item
    for item in properties
}
selected_label = st.selectbox("Property", list(property_options))
selected = property_options[selected_label]

campaign = st.text_input(
    "Campaign name",
    value=f"social_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
    help="The same campaign name is used across all three channels while the channel attribution remains separate.",
).strip()

if not campaign:
    st.warning("Enter a campaign name before creating the packages.")
    st.stop()

all_links = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
links_by_channel = {row["Channel key"]: row["Tracked Dwelyx link"] for row in all_links}

packages = {}
for channel_key in SOCIAL_CHANNEL_KEYS:
    channel = CHANNELS_BY_KEY[channel_key]
    try:
        packages[channel_key] = build_social_video_package(
            selected,
            channel_key=channel.key,
            channel_name=channel.name,
            tracked_link=links_by_channel[channel.key],
        )
    except SocialVideoPackageError as exc:
        st.error(f"Social content fact guard blocked this property: {exc}")
        st.info("Correct the property facts in Record Manager, then return to this page.")
        st.stop()

metrics = st.columns(4)
metrics[0].metric("Channels built", "3")
metrics[1].metric("Campaign", campaign)
metrics[2].metric("Property", selected.city or selected.state or "Saved property")
metrics[3].metric("Attribution", "Separate by channel")

st.write("### Short-form channel packages")
tabs = st.tabs([CHANNELS_BY_KEY[key].name for key in SOCIAL_CHANNEL_KEYS])

for tab, channel_key in zip(tabs, SOCIAL_CHANNEL_KEYS, strict=True):
    package = packages[channel_key]
    with tab:
        st.write(f"### {package.channel_name}")
        st.text_input("Hook", value=package.hook, key=f"hook_{channel_key}")
        st.text_area(
            "Ready-to-use caption / post copy",
            value=package.caption,
            height=260,
            key=f"caption_{channel_key}",
        )
        st.text_area(
            "30–45 second video script",
            value=package.short_script,
            height=220,
            key=f"script_{channel_key}",
        )
        st.write("**Shot list**")
        for index, shot in enumerate(package.shot_list, start=1):
            st.write(f"{index}. {shot}")
        st.write("**Call to action**")
        st.write(package.call_to_action)
        st.text_input(
            "Tracked Dwelyx link",
            value=package.tracked_link,
            key=f"link_{channel_key}",
        )
        st.link_button(
            f"Test {package.channel_name} Link",
            package.tracked_link,
        )
        st.caption(
            f"Traffic through this link is attributed to {package.channel_name}, campaign {campaign}, and this property."
        )

st.write("### Attribution summary")
summary_frame = pd.DataFrame(
    [
        {
            "Channel": packages[key].channel_name,
            "Campaign": campaign,
            "Property": selected_label,
            "Tracked Dwelyx Link": packages[key].tracked_link,
        }
        for key in SOCIAL_CHANNEL_KEYS
    ]
)
st.dataframe(summary_frame, use_container_width=True, hide_index=True)
st.download_button(
    "Download Social Channel Package Links",
    summary_frame.to_csv(index=False).encode("utf-8"),
    f"social-short-form-{selected.property_id}.csv",
    "text/csv",
)

st.warning(
    "Publishing remains approval-controlled. Keep the property visually truthful in every video; do not hide defects, unfinished work, clutter, or other material condition shown in the source footage."
)
st.caption(
    "Long-form YouTube walkthrough editing, AI narration, music, and MP4 rendering are intentionally deferred to the later video-engine build."
)
