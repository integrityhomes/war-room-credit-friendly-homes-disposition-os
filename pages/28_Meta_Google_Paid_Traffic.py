from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.paid_traffic_channels import PaidTrafficPackageError, build_paid_traffic_package
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(page_title="Meta & Google Paid Traffic", page_icon="📈", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    with st.form("paid_traffic_login"):
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
st.title("Meta Housing Ads + Google Search Ads")
st.caption("Create paid-traffic packages that stay separately attributable by channel, campaign, and property.")
st.info("Nothing is published or charged from this page. Final platform setup, targeting, and spend remain manager-approved.")

try:
    properties = get_storage().list_properties()
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("Add a property before creating paid traffic campaigns.")
    st.stop()

options = {(item.display_address or str(item.property_id)): item for item in properties}
selected = options[st.selectbox("Property", list(options))]
campaign = st.text_input("Campaign name", value=f"paid_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower()).strip()

budget_cols = st.columns(2)
daily_budget = Decimal(str(budget_cols[0].number_input("Daily budget", min_value=1.0, value=20.0, step=5.0)))
monthly_cap = Decimal(str(budget_cols[1].number_input("Monthly budget cap", min_value=1.0, value=600.0, step=50.0)))

links = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
links_by_key = {row["Channel key"]: row["Tracked Dwelyx link"] for row in links}

channel_keys = ("meta_ads", "google_ads")
tabs = st.tabs([CHANNELS_BY_KEY[key].name for key in channel_keys])
export_rows: list[dict[str, str]] = []

for tab, key in zip(tabs, channel_keys, strict=True):
    channel = CHANNELS_BY_KEY[key]
    with tab:
        try:
            package = build_paid_traffic_package(
                selected,
                channel_key=key,
                channel_name=channel.name,
                tracked_link=links_by_key[key],
                campaign_name=campaign,
                daily_budget=daily_budget,
                monthly_budget_cap=monthly_cap,
            )
        except PaidTrafficPackageError as exc:
            st.error(f"Campaign guard blocked this package: {exc}")
            continue

        cols = st.columns(4)
        cols[0].metric("Channel", channel.name)
        cols[1].metric("Daily budget", f"${package.daily_budget:,.0f}")
        cols[2].metric("Monthly cap", f"${package.monthly_budget_cap:,.0f}")
        cols[3].metric("Launch", "Manager approval")

        st.write("### Headline options")
        st.dataframe(pd.DataFrame({"Headline": package.headline_options}), use_container_width=True, hide_index=True)

        st.write("### Ad copy options")
        for index, copy in enumerate(package.primary_text_options, start=1):
            st.text_area(f"Variation {index}", value=copy, height=130, key=f"{key}_copy_{index}")
            export_rows.append({
                "channel": channel.name,
                "channel_key": key,
                "campaign": campaign,
                "property": selected.display_address,
                "variation": str(index),
                "headline": package.headline_options[min(index - 1, len(package.headline_options) - 1)],
                "copy": copy,
                "tracked_dwelyx_link": package.tracked_link,
                "daily_budget": str(package.daily_budget),
                "monthly_budget_cap": str(package.monthly_budget_cap),
            })

        st.write("### Tracked Dwelyx link")
        st.code(package.tracked_link, language=None)
        st.caption("Use this exact destination so traffic and downstream buyer results stay attributed to this paid channel and campaign.")

        st.write("### Final approval checklist")
        for note in package.approval_notes:
            st.write(f"- {note}")

if export_rows:
    csv_bytes = pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Meta + Google campaign package CSV",
        data=csv_bytes,
        file_name=f"{campaign}_paid_traffic.csv",
        mime="text/csv",
    )

st.warning(
    "Before launch, verify the property is still available, verify all terms, review the current "
    "platform housing/financial-services requirements, and approve the budget and targeting. "
    "Do not promise buyer approval."
)
