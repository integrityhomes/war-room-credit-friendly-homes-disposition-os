from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.fact_lock import MARKETABLE_PROPERTY_STATUSES
from cfh_disposition.go_live_connections import build_connection_status
from cfh_disposition.paid_traffic_channels import (
    PaidTrafficPackageError,
    build_paid_traffic_package,
)
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
st.caption(
    "Create fact-locked paid-traffic planning packages that remain separately attributable by channel, campaign, and property."
)
st.info(
    "This is a planning and approval-preparation page only. It cannot create an ad, activate a campaign, or spend money. "
    "Actual platform connection, targeting, launch, and spend remain owner-approved external steps."
)

try:
    properties = [
        item
        for item in get_storage().list_properties()
        if item.status in MARKETABLE_PROPERTY_STATUSES
    ]
except StorageError as exc:
    st.error(f"Property storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning(
        "No Ready to Launch or Marketing Live property is available for paid-traffic planning."
    )
    st.stop()

options = {(item.display_address or str(item.property_id)): item for item in properties}
selected = options[st.selectbox("Property", list(options))]
campaign = st.text_input(
    "Campaign name",
    value=f"paid_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
).strip()
if not campaign:
    st.warning("Enter a campaign name before creating a paid-traffic package.")
    st.stop()

budget_cols = st.columns(2)
daily_budget = Decimal(
    str(
        budget_cols[0].number_input(
            "Proposed daily budget",
            min_value=1.0,
            value=20.0,
            step=5.0,
            help="Planning value only. Entering a number here does not authorize or spend money.",
        )
    )
)
monthly_cap = Decimal(
    str(
        budget_cols[1].number_input(
            "Proposed monthly budget cap",
            min_value=1.0,
            value=600.0,
            step=50.0,
            help="Planning value only. The owner must separately approve any real campaign spend.",
        )
    )
)

connections = {row.key: row for row in build_connection_status(st.secrets)}
connection_cols = st.columns(2)
for column, key, label in (
    (connection_cols[0], "meta_ads", "Meta Ads"),
    (connection_cols[1], "google_ads", "Google Ads"),
):
    row = connections[key]
    column.metric(f"{label} connection", "Present" if row.configured else "Not connected")
    if row.configured:
        column.caption("Connection details are present. This page still cannot launch or spend.")
    else:
        column.caption("No live platform connection is configured yet.")

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
        cols[1].metric("Proposed daily budget", f"${package.daily_budget:,.0f}")
        cols[2].metric("Proposed monthly cap", f"${package.monthly_budget_cap:,.0f}")
        cols[3].metric("External launch", "Owner approval required")

        st.write("### Fact-locked headline options")
        st.dataframe(
            pd.DataFrame({"Headline": package.headline_options}),
            use_container_width=True,
            hide_index=True,
        )

        st.write("### Fact-locked ad copy options")
        for index, copy in enumerate(package.primary_text_options, start=1):
            st.text_area(
                f"Variation {index}",
                value=copy,
                height=130,
                key=f"{key}_copy_{index}",
                disabled=True,
            )
            export_rows.append(
                {
                    "channel": channel.name,
                    "channel_key": key,
                    "campaign": campaign,
                    "property": selected.display_address,
                    "variation": str(index),
                    "headline": package.headline_options[
                        min(index - 1, len(package.headline_options) - 1)
                    ],
                    "copy": copy,
                    "tracked_dwelyx_link": package.tracked_link,
                    "proposed_daily_budget": str(package.daily_budget),
                    "proposed_monthly_budget_cap": str(package.monthly_budget_cap),
                    "spend_authorized": "NO",
                    "launch_authorized": "NO",
                }
            )

        st.write("### Tracked Dwelyx link")
        st.code(package.tracked_link, language=None)
        st.caption(
            "Use this exact destination if a future owner-approved campaign is created so traffic and downstream buyer results stay attributed to this paid channel and campaign."
        )

        st.write("### Required owner review before any external launch")
        for note in package.approval_notes:
            st.write(f"- {note}")
        st.warning(
            "No approval is recorded by viewing or downloading this package. No campaign may be activated and no budget may be spent until the owner approval workflow records a separate approval."
        )

if export_rows:
    csv_bytes = pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Meta + Google planning package CSV",
        data=csv_bytes,
        file_name=f"{campaign}_paid_traffic_planning.csv",
        mime="text/csv",
    )

st.warning(
    "Before any future launch: verify the property is still available, verify all terms, review current platform housing/financial-services requirements, and obtain explicit owner approval for the exact budget and targeting. Do not promise buyer approval."
)
