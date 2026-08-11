from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Property Channel Tracking Links",
    page_icon="🔗",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Property Channel Tracking Links")
    st.caption("Private internal access")
    with st.form("tracking_links_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_property_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


def property_label(item) -> str:
    return item.display_address or str(item.property_id)


require_password()
st.title("Property Channel Tracking Links")
st.caption(
    "Generate the exact property link to use in each marketing channel so Dwelyx results can be attributed back to the source that produced them."
)
st.info(
    "Use the generated link in the actual post, ad, text, email, QR code, or campaign. Do not replace it with the raw Dwelyx URL or the channel attribution will be lost."
)

try:
    properties = get_property_storage().list_properties()
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("Add a property to Credit Friendly Homes before generating tracking links.")
    st.stop()

property_options = {property_label(item): item for item in properties}
selected_property_label = st.selectbox("Property", list(property_options))
selected_property = property_options[selected_property_label]

left, right = st.columns(2)
selected_channel = left.selectbox(
    "Marketing channel",
    CHANNELS,
    format_func=lambda item: item.name,
)
campaign = right.text_input(
    "Campaign name",
    value="owner_finance_homes",
    help="Use a short name that tells you which campaign or push this link belongs to, such as decatur_august_2026.",
).strip()

if not campaign:
    st.warning("Enter a campaign name before generating the link.")
    st.stop()

rows = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected_property.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
by_channel = {row["Channel key"]: row for row in rows}
selected_row = by_channel[selected_channel.key]
tracked_link = selected_row["Tracked Dwelyx link"]

st.write("### Link to use")
with st.container(border=True):
    summary = st.columns(3)
    summary[0].write("**Property**")
    summary[0].write(selected_property_label)
    summary[1].write("**Channel**")
    summary[1].write(selected_channel.name)
    summary[2].write("**Campaign**")
    summary[2].write(campaign)

    st.code(tracked_link, language=None)
    st.caption(
        "Copy this exact link into the selected channel. Buyer activity that reaches Dwelyx can then roll back into the Results & Attribution Center under this property, channel, and campaign."
    )

st.write("### All 15 channel links for this property")
link_frame = pd.DataFrame(
    [
        {
            "Channel": row["Channel"],
            "Mode": row["Mode"],
            "Campaign": campaign,
            "Tracked Link": row["Tracked Dwelyx link"],
        }
        for row in rows
    ]
)
st.dataframe(link_frame, use_container_width=True, hide_index=True)
st.download_button(
    "Download All Property Tracking Links",
    link_frame.to_csv(index=False).encode("utf-8"),
    f"property-{selected_property.property_id}-tracking-links.csv",
    "text/csv",
)

st.caption(
    "This page creates attribution links only. It does not publish ads, book showings, change Dwelyx, or alter buyer records."
)
