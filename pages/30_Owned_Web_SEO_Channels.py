from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.owned_web_channels import OwnedWebPackageError, build_owned_web_package
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(page_title="Owned Web + SEO Channels", page_icon="🌐", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    with st.form("owned_web_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


require_password()
st.title("Property Landing Page + Blog + City & Market SEO")
st.caption("Build the three Credit Friendly Homes owned-web channels with separate Dwelyx attribution.")

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("Add a property before creating owned-web content.")
    st.stop()

options = {(item.display_address or str(item.property_id)): item for item in properties}
selected = options[st.selectbox("Property", list(options))]
campaign = st.text_input(
    "Campaign name",
    value=f"owned_web_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
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

channel_keys = ("property_page", "blog", "market_seo")
tabs = st.tabs([CHANNELS_BY_KEY[key].name for key in channel_keys])
export_rows: list[dict[str, str]] = []

for tab, key in zip(tabs, channel_keys, strict=True):
    channel = CHANNELS_BY_KEY[key]
    with tab:
        try:
            package = build_owned_web_package(
                selected,
                channel_key=key,
                channel_name=channel.name,
                tracked_link=links_by_key[key],
            )
        except OwnedWebPackageError as exc:
            st.error(f"Content guard blocked this package: {exc}")
            continue

        st.write("### SEO title")
        st.code(package.title, language=None)
        st.write("### Meta description")
        st.text_area(f"{channel.name} meta description", package.meta_description, height=100, key=f"meta_{key}")
        st.write("### Headline")
        st.code(package.headline, language=None)
        st.write("### Page / article copy")
        st.text_area(f"{channel.name} copy", package.body, height=220, key=f"body_{key}")
        st.write("### Keyword targets")
        st.dataframe(pd.DataFrame({"Keyword": package.keyword_targets}), use_container_width=True, hide_index=True)
        st.write("### Tracked Dwelyx link")
        st.code(package.tracked_link, language=None)
        st.caption(
            "Use this exact link so downstream buyer activity stays attributed to this owned-web channel, campaign, and property."
        )

        export_rows.append({
            "channel": channel.name,
            "channel_key": key,
            "campaign": campaign,
            "property": selected.display_address,
            "title": package.title,
            "meta_description": package.meta_description,
            "headline": package.headline,
            "body": package.body,
            "keywords": " | ".join(package.keyword_targets),
            "tracked_dwelyx_link": package.tracked_link,
        })

if export_rows:
    csv_bytes = pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download owned-web + SEO package CSV",
        data=csv_bytes,
        file_name=f"{campaign}_owned_web_seo.csv",
        mime="text/csv",
    )

st.warning(
    "Before publishing, verify current property availability and terms. Do not create approval guarantees, "
    "misleading urgency, or facts that are not present in the saved property record."
)
