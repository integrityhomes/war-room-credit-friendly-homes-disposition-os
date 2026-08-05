from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.nextdoor import (
    NEXTDOOR_BODY_LIMIT,
    NEXTDOOR_CTA_LIMIT,
    NEXTDOOR_HEADLINE_LIMIT,
    NEXTDOOR_IMAGE_SPECS,
    NextdoorPackageError,
    build_nextdoor_package,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Nextdoor Channel 15",
    page_icon="🏘️",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Nextdoor Channel 15")
    st.caption("Private internal access")
    with st.form("nextdoor_login"):
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
st.title("Nextdoor Channel 15")
st.caption(
    "Creates fact-safe Nextdoor Business Posts and paid housing-ad packages that send buyers to Dwelyx."
)
st.info(
    "The app prepares and tracks the package. A team member must complete Business Page verification, final publication, targeting review, and any paid-ad budget approval inside Nextdoor."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
except StorageError as exc:
    st.error(f"Nextdoor Channel 15 could not load saved properties: {exc}")
    st.stop()

if not properties:
    st.warning("Add and save a property before creating a Nextdoor package.")
    st.stop()

property_options = {
    item.display_address or str(item.property_id): item
    for item in properties
}
selected_name = st.selectbox("Choose property", list(property_options))
selected = property_options[selected_name]

campaign = st.text_input(
    "Campaign name",
    value=f"nextdoor_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
    help="This name is included in the tracked Dwelyx attribution.",
)

links = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
nextdoor_row = next(row for row in links if row["Channel key"] == "nextdoor")
tracked_link = nextdoor_row["Tracked Dwelyx link"]

try:
    package = build_nextdoor_package(selected, tracked_link)
except NextdoorPackageError as exc:
    st.error(f"Nextdoor fact guard blocked this property package: {exc}")
    st.info("Correct the property facts in Record Manager, then return to this page.")
    st.stop()

if selected.photo_urls:
    st.image(str(selected.photo_urls[0]), width=480)
else:
    st.warning("This property has no saved marketing photo. Add clear property photos before publishing on Nextdoor.")

metrics = st.columns(5)
metrics[0].metric("Channel", "15")
metrics[1].metric("Property Status", selected.status.value)
metrics[2].metric(
    "Down Payment",
    f"${selected.down_payment:,.0f}" if selected.down_payment is not None else "Missing",
)
metrics[3].metric(
    "Monthly Payment",
    f"${selected.monthly_payment:,.0f}" if selected.monthly_payment is not None else "Missing",
)
metrics[4].metric("Final Publication", "Manual")

st.text_input("Tracked Nextdoor → Dwelyx link", value=tracked_link)
st.link_button("Test Nextdoor Dwelyx Link", tracked_link, type="primary")
st.caption(
    "Testing the link records one Nextdoor-attributed click before opening Dwelyx. This app does not create a second buyer database."
)

business_tab, paid_tab, setup_tab = st.tabs(
    ["Organic Business Post", "Paid Housing Ad", "Setup & Compliance"]
)

with business_tab:
    st.write("### Nextdoor Business Post")
    st.text_input(
        f"Post title — {len(package.business_post_title)} of {NEXTDOOR_HEADLINE_LIMIT} characters",
        value=package.business_post_title,
    )
    st.text_area(
        f"Copy-ready Business Post — {len(package.business_post_body)} of {NEXTDOOR_BODY_LIMIT} characters",
        value=package.business_post_body,
        height=420,
    )
    st.success("Use this post from a claimed and verified Nextdoor Business Page. Final publication remains manual.")

with paid_tab:
    st.write("### Nextdoor Paid Housing Ad")
    st.warning(
        "Do not spend money until a manager approves the campaign budget, audience settings, final creative, destination, and reporting plan."
    )
    st.text_input(
        f"Ad headline — {len(package.paid_ad_headline)} of {NEXTDOOR_HEADLINE_LIMIT} characters",
        value=package.paid_ad_headline,
    )
    st.text_area(
        f"Ad body — {len(package.paid_ad_body)} of {NEXTDOOR_BODY_LIMIT} characters",
        value=package.paid_ad_body,
        height=420,
    )
    st.text_input(
        f"Call to action — {len(package.paid_ad_cta)} of {NEXTDOOR_CTA_LIMIT} characters",
        value=package.paid_ad_cta,
    )
    st.write(f"**Recommended image specifications:** {NEXTDOOR_IMAGE_SPECS}")
    st.info(
        "The paid-ad package uses the same tracked Dwelyx destination as the organic post so clicks can be attributed to Nextdoor. Record organic and paid results separately in the AI Marketing Optimizer notes."
    )

with setup_tab:
    st.write("### Required operating steps")
    instruction_rows = [
        {"Step": index, "Requirement": instruction}
        for index, instruction in enumerate(package.publication_instructions, start=1)
    ]
    st.dataframe(pd.DataFrame(instruction_rows), use_container_width=True, hide_index=True)

    st.write("### Before the first post")
    st.write(
        "Claim and verify the Credit Friendly Homes Nextdoor Business Page, confirm the business identity and service area, upload approved branding, and review current housing-ad rules inside the platform."
    )
    st.write("### Never automate")
    st.write(
        "Do not use browser bots, fake neighbor accounts, account sharing, policy evasion, or unsupported bulk neighborhood posting. The team must confirm each post or ad actually went live before marking it Posted."
    )
    st.write("### Reporting")
    st.write(
        "Track impressions, platform clicks, tracked Dwelyx clicks, inquiries, applications, contracts, and spend. Nextdoor now appears as its own row in the 15-channel analytics and marketing optimizer."
    )
