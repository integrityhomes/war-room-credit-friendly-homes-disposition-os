from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.app_secrets import get_secrets
from cfh_disposition.auth import require_password
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.classifieds_channel import (
    ClassifiedsPackageError,
    build_classifieds_package,
)
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(page_title="Craigslist & Local Classifieds", page_icon="📌", layout="wide")

@st.cache_resource
def get_storage():
    return build_storage(get_secrets(), SAMPLE_PROPERTIES, SAMPLE_BUYERS)

def property_label(item) -> str:
    return item.display_address or str(item.property_id)

require_password()
st.title("Craigslist & Local Classifieds")
st.caption(
    "Create one fact-safe classified package with a tracked Dwelyx link so registrations, applications, showings, contracts, and filled homes remain attributable to the classifieds channel."
)
st.info(
    "This is assisted posting. The app prepares the listing package; the team still reviews and publishes the final classified manually."
)

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("Add a property before creating classified packages.")
    st.stop()

property_options = {property_label(item): item for item in properties}
selected_label = st.selectbox("Property", list(property_options))
selected = property_options[selected_label]

campaign = st.text_input(
    "Campaign name",
    value=f"classifieds_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
).strip()
if not campaign:
    st.warning("Enter a campaign name.")
    st.stop()

links = build_channel_links(
    dwelyx_base_url(get_secrets()),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(get_secrets()),
)
links_by_key = {row["Channel key"]: row["Tracked Dwelyx link"] for row in links}
channel = CHANNELS_BY_KEY["classifieds"]

try:
    package = build_classifieds_package(
        selected,
        tracked_link=links_by_key["classifieds"],
        channel_name=channel.name,
    )
except ClassifiedsPackageError as exc:
    st.error(f"Fact guard blocked this package: {exc}")
    st.stop()

metrics = st.columns(4)
metrics[0].metric("Channel", channel.name)
metrics[1].metric("Mode", channel.mode.value)
metrics[2].metric("Campaign", campaign)
metrics[3].metric("Variations", len(package.body_variants))

st.write("### Headline")
st.code(package.headline, language=None)

st.write("### Ready-to-post variations")
tabs = st.tabs(["Full Listing A", "Full Listing B", "Shorter Listing"])
for index, (tab, body) in enumerate(zip(tabs, package.body_variants, strict=True), start=1):
    with tab:
        st.text_area(
            f"Classified copy variation {index}",
            value=body,
            height=330,
            key=f"classified_body_{index}",
        )

st.write("### Compact version")
st.text_area("Compact classified copy", value=package.short_body, height=160)

st.write("### Verified facts used")
st.dataframe(
    pd.DataFrame([{"Fact": fact} for fact in package.fact_summary]),
    use_container_width=True,
    hide_index=True,
)

st.write("### Posting checklist")
st.dataframe(
    pd.DataFrame(
        [{"Step": index, "Check": item} for index, item in enumerate(package.posting_checklist, start=1)]
    ),
    use_container_width=True,
    hide_index=True,
)

st.write("### Tracked Dwelyx link")
st.code(package.tracked_link, language=None)
st.caption(
    "Use this exact link in the classified so the Results Dashboard can attribute downstream Dwelyx activity to Craigslist & Local Classifieds, this campaign, and this property."
)

csv_rows = [
    {
        "property": selected.display_address,
        "campaign": campaign,
        "channel": package.channel_name,
        "variation": index,
        "headline": package.headline,
        "copy": body,
        "tracked_dwelyx_link": package.tracked_link,
    }
    for index, body in enumerate(package.body_variants, start=1)
]
st.download_button(
    "Download classified package CSV",
    pd.DataFrame(csv_rows).to_csv(index=False).encode("utf-8"),
    file_name=f"classifieds_{str(selected.property_id)[:8]}_{campaign}.csv",
    mime="text/csv",
)

st.warning(
    "Before posting or refreshing: verify availability and terms, use current property media, keep the tracked link intact, and review the final copy."
)
