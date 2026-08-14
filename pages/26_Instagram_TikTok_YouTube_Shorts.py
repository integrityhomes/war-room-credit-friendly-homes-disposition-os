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
    "Creates ready-to-post short-form social packages for each platform while keeping Dwelyx attribution separate by channel, campaign, and property."
)
st.info(
    "Each platform gets its own tracked Dwelyx link plus platform-specific titles, caption variations, hashtags, on-screen text, scripts, and posting notes."
)

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Social video channels could not load saved properties: {exc}")
    st.stop()

if not properties:
    st.warning("Add and save a property before creating social content.")
    st.stop()

property_options = {item.display_address or str(item.property_id): item for item in properties}
selected_label = st.selectbox("Choose property", list(property_options))
selected = property_options[selected_label]

campaign = st.text_input(
    "Campaign name",
    value=f"social_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
    help="The same campaign name is used across all three channels so the Results Center can compare performance cleanly.",
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
summary[2].metric("Caption variations", "9 total")
summary[3].metric("Attribution", "Separate by channel")

st.write("### Ready-to-post packages")
tabs = st.tabs([name for _, name in SOCIAL_CHANNELS])
for tab, (channel_key, channel_name) in zip(tabs, SOCIAL_CHANNELS, strict=True):
    package = packages[channel_key]
    with tab:
        st.write(f"#### {channel_name}")
        st.text_input("Post / video title", value=package.post_title, key=f"title_{channel_key}")
        st.text_input("Tracked Dwelyx link", value=package.tracked_link, key=f"link_{channel_key}")

        st.write("**Hook**")
        st.code(package.hook, language=None)

        st.write("**Caption variations**")
        for index, caption in enumerate(package.caption_variants, start=1):
            st.text_area(
                f"Variation {index}",
                value=caption,
                height=220,
                key=f"caption_{channel_key}_{index}",
            )

        st.write("**Hashtags**")
        st.code(" ".join(package.hashtags), language=None)

        st.write("**30–45 second script guide**")
        st.text_area(
            "Short-form script",
            value=package.short_script,
            height=220,
            key=f"script_{channel_key}",
        )

        st.write("**On-screen text sequence**")
        on_screen_rows = [
            {"Order": index, "Text": text}
            for index, text in enumerate(package.on_screen_text, start=1)
        ]
        st.dataframe(pd.DataFrame(on_screen_rows), use_container_width=True, hide_index=True)

        st.write("**Recommended shot order**")
        shot_rows = [
            {"Order": index, "Shot": shot}
            for index, shot in enumerate(package.shot_list, start=1)
        ]
        st.dataframe(pd.DataFrame(shot_rows), use_container_width=True, hide_index=True)

        st.write("**Posting notes**")
        for note in package.posting_notes:
            st.write(f"- {note}")

        st.write(f"**Call to action:** {package.call_to_action}")
        st.caption(
            "Final publication stays approval-controlled. Keep the exact tracked link with the platform content so downstream buyer activity remains attributable."
        )

st.write("### Downloadable three-channel posting pack")
posting_rows = []
for channel_key, channel_name in SOCIAL_CHANNELS:
    package = packages[channel_key]
    for variation_number, caption in enumerate(package.caption_variants, start=1):
        posting_rows.append(
            {
                "Channel": channel_name,
                "Campaign": campaign,
                "Property": selected_label,
                "Variation": variation_number,
                "Title": package.post_title,
                "Caption": caption,
                "Hashtags": " ".join(package.hashtags),
                "Script": package.short_script,
                "Tracked Dwelyx Link": package.tracked_link,
            }
        )

posting_frame = pd.DataFrame(posting_rows)
st.dataframe(posting_frame, use_container_width=True, hide_index=True)
st.download_button(
    "Download Ready-to-Post Social Pack",
    posting_frame.to_csv(index=False).encode("utf-8"),
    f"property-{selected.property_id}-social-posting-pack.csv",
    "text/csv",
)

st.warning(
    "Before posting: confirm the property is still available, verify current terms, and review the photos or video. Do not alter the property condition or add unverified claims."
)
st.caption(
    "Long-form YouTube walkthrough editing, AI narration, music, and rendered downloadable video remain intentionally deferred to the later video-engine build."
)
