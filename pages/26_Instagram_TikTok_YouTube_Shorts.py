from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.social_video_channels import (
    SocialVideoPackageError,
    build_social_video_package,
)
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Instagram + TikTok + YouTube Shorts",
    page_icon="🎬",
    layout="wide",
)

SOCIAL_CHANNELS = (
    ("instagram", "Instagram Reels & Posts"),
    ("tiktok", "TikTok"),
    ("youtube", "YouTube Shorts"),
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Instagram + TikTok + YouTube Shorts")
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


require_password()
st.title("Instagram Reels + TikTok + YouTube Shorts")
st.caption(
    "Builds three separate, fact-safe social packages from one property while preserving channel-specific Dwelyx attribution."
)
st.info(
    "Each channel gets its own tracked link. Use the exact link supplied for that platform "
    "so registrations, applications, showings, contracts, and filled homes can be attributed "
    "back to Instagram, TikTok, or YouTube."
)

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Social video channels could not load saved properties: {exc}")
    st.stop()

if not properties:
    st.warning("Add and save a property before creating social content.")
    st.stop()

property_options = {
    item.display_address or str(item.property_id): item
    for item in properties
}
selected_label = st.selectbox("Choose property", list(property_options))
selected = property_options[selected_label]

campaign = st.text_input(
    "Campaign name",
    value=f"social_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
    help="This campaign name stays attached to all three channel links so the Results Center can compare them cleanly.",
).strip()
if not campaign:
    st.warning("Enter a campaign name before creating the packages.")
    st.stop()

link_rows = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
links_by_channel = {row["Channel key"]: row["Tracked Dwelyx link"] for row in link_rows}

packages = {}
for channel_key, channel_name in SOCIAL_CHANNELS:
    try:
        packages[channel_key] = build_social_video_package(
            selected,
            channel_key=channel_key,
            channel_name=channel_name,
            tracked_link=links_by_channel[channel_key],
        )
    except SocialVideoPackageError as exc:
        st.error(f"Social fact guard blocked this property: {exc}")
        st.info("Correct the property facts in Record Manager, then return to this page.")
        st.stop()

summary = st.columns(4)
summary[0].metric("Property", selected.city or selected.state or "Saved property")
summary[1].metric("Platforms", "3")
summary[2].metric("Campaign", campaign)
summary[3].metric("Attribution", "Separate by channel")

st.write("### Content packages")
tabs = st.tabs([name for _, name in SOCIAL_CHANNELS])
for tab, (channel_key, channel_name) in zip(tabs, SOCIAL_CHANNELS, strict=True):
    package = packages[channel_key]
    with tab:
        st.write(f"#### {channel_name}")
        st.text_input("Tracked Dwelyx link", value=package.tracked_link, key=f"link_{channel_key}")
        st.write("**Hook**")
        st.code(package.hook, language=None)
        st.write("**Caption / post copy**")
        st.text_area(
            "Copy-ready post",
            value=package.caption,
            height=260,
            key=f"caption_{channel_key}",
        )
        st.write("**30–45 second voice/script guide**")
        st.text_area(
            "Short-form script",
            value=package.short_script,
            height=220,
            key=f"script_{channel_key}",
        )
        st.write("**Recommended shot order**")
        shot_rows = [
            {"Order": index, "Shot": shot}
            for index, shot in enumerate(package.shot_list, start=1)
        ]
        st.dataframe(pd.DataFrame(shot_rows), use_container_width=True, hide_index=True)
        st.write(f"**Call to action:** {package.call_to_action}")
        st.caption(
            "Final publication stays approval-controlled. Do not replace the tracked link with a raw Dwelyx URL."
        )

st.write("### Three-channel tracking summary")
tracking_frame = pd.DataFrame(
    [
        {
            "Channel": channel_name,
            "Campaign": campaign,
            "Property": selected_label,
            "Tracked Dwelyx Link": packages[channel_key].tracked_link,
        }
        for channel_key, channel_name in SOCIAL_CHANNELS
    ]
)
st.dataframe(tracking_frame, use_container_width=True, hide_index=True)
st.download_button(
    "Download Social Channel Package Links",
    tracking_frame.to_csv(index=False).encode("utf-8"),
    f"property-{selected.property_id}-social-links.csv",
    "text/csv",
)

st.caption(
    "Long-form YouTube walkthrough video editing, AI narration, music, and downloadable rendered video are intentionally deferred to the later video-engine build."
)
