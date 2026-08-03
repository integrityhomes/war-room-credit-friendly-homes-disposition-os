from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channels import CHANNELS
from cfh_disposition.content import build_deterministic_campaign_draft
from cfh_disposition.dwelyx import build_dwelyx_url, dwelyx_base_url
from cfh_disposition.launch_plan import build_launch_plan
from cfh_disposition.marketplace import review_marketplace_copy
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.public_pages import public_portal_path, public_property_path, render_public_request
from cfh_disposition.record_manager import render_record_manager
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, SupabaseSettings, build_storage

st.set_page_config(page_title="Credit Friendly Homes Disposition OS", page_icon="🏠", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.code('APP_PASSWORD = "choose-a-strong-private-password"')
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("Credit Friendly Homes Disposition OS")
    st.caption("Private internal access")
    with st.form("login_form"):
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


def load_records(force: bool = False) -> None:
    if st.session_state.get("records_loaded") and not force:
        return
    storage = get_storage()
    try:
        st.session_state.properties = storage.list_properties()
        st.session_state.buyers = storage.list_buyers()
        st.session_state.storage_error = ""
    except StorageError as exc:
        st.session_state.properties = []
        st.session_state.buyers = []
        st.session_state.storage_error = str(exc)
    st.session_state.records_loaded = True


def money(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:,.0f}"


def property_options() -> dict[str, OwnerFinanceProperty]:
    return {item.display_address or str(item.property_id): item for item in st.session_state.properties}


def save_property(record: OwnerFinanceProperty) -> None:
    storage = get_storage()
    storage.save_property(record)
    current = {str(item.property_id): item for item in st.session_state.properties}
    current[str(record.property_id)] = record
    st.session_state.properties = list(current.values())


storage = get_storage()
if render_public_request(storage):
    st.stop()

require_password()
load_records()

st.title("Credit Friendly Homes Disposition OS")
st.caption("Owner-finance marketing, Dwelyx traffic, landing pages, compliance, and launch automation.")

storage = get_storage()
settings = SupabaseSettings.from_mapping(st.secrets)
dwelyx_url = dwelyx_base_url(st.secrets)
st.sidebar.success(f"Storage: {storage.mode}")
if st.sidebar.button("Refresh saved records"):
    load_records(force=True)
    st.rerun()
if st.sidebar.button("Log out"):
    st.session_state.authenticated = False
    st.rerun()

page = st.sidebar.radio(
    "Navigation",
    [
        "Executive War Room",
        "Property Intake",
        "Record Manager",
        "Campaign Readiness",
        "Dwelyx Traffic Hub",
        "Marketplace Guard",
        "System Setup",
        "Build Roadmap",
    ],
)
st.sidebar.info("Public repository mode: credentials and real records belong only in Streamlit Secrets and Supabase.")

if st.session_state.get("storage_error"):
    st.error(st.session_state.storage_error)
    st.warning("Open System Setup and confirm the Supabase connection before entering records.")

if page == "Executive War Room":
    properties = st.session_state.properties
    launch_ready = sum(item.status == PropertyStatus.READY for item in properties)
    marketing_live = sum(item.status == PropertyStatus.LIVE for item in properties)
    needs_information = sum(item.status == PropertyStatus.NEEDS_INFORMATION for item in properties)

    columns = st.columns(4)
    values = [
        ("Properties", len(properties)),
        ("Launch Ready", launch_ready),
        ("Marketing Live", marketing_live),
        ("Needs Information", needs_information),
    ]
    for column, (label, value) in zip(columns, values, strict=True):
        column.metric(label, value)

    st.link_button(
        "Open Dwelyx — Full Owner-Finance Marketplace",
        build_dwelyx_url(dwelyx_url, source="credit_friendly_homes", medium="executive_war_room"),
        type="primary",
    )
    st.markdown(f"[Open featured-homes landing portal]({public_portal_path()})")

    rows = []
    for item in properties:
        plan = build_launch_plan(item)
        rows.append(
            {
                "Property": item.display_address,
                "Status": item.status,
                "Price": money(item.total_price),
                "Down": money(item.down_payment),
                "Monthly": money(item.monthly_payment),
                "Launch Ready": "Yes" if plan.can_launch else "No",
                "Blocking Issues": len(plan.validation.errors),
            }
        )
    st.subheader("Property Disposition Board")
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No properties saved yet. Add the first one in Property Intake.")

    st.subheader("14-Channel Growth Plan")
    channel_rows = [{"Channel": item.name, "Mode": item.mode, "Purpose": item.purpose} for item in CHANNELS]
    st.dataframe(pd.DataFrame(channel_rows), use_container_width=True, hide_index=True)

elif page == "Property Intake":
    st.subheader("Add an Owner-Finance Property")
    if not settings.configured:
        st.warning("Demo mode is active. Connect Supabase before entering real property information.")

    with st.form("property_intake", clear_on_submit=False):
        left, middle, right = st.columns(3)
        address = left.text_input("Street address*")
        city = middle.text_input("City*")
        state = right.text_input("State abbreviation*", max_chars=2)
        zip_code = left.text_input("ZIP code*")
        county = middle.text_input("County")
        bedrooms = right.number_input("Bedrooms*", min_value=0, max_value=20, value=3)
        bathrooms = left.number_input("Bathrooms*", min_value=0.0, max_value=20.0, value=1.0, step=0.5)
        total_price = middle.text_input("Total price*", value="100000")
        down_payment = right.text_input("Down payment*", value="5000")
        monthly_payment = left.text_input("Monthly payment*", value="1200")
        condition = st.text_area("Condition summary*")
        repairs = st.text_area("Known repairs needed")
        showing = st.text_area("Showing instructions*")
        disclosures = st.text_area("Public disclosures*")
        photo_text = st.text_area("Photo URLs* — one per line")
        application_url = st.text_input("Dwelyx property listing URL — optional")
        submitted = st.form_submit_button("Validate and Save Property", type="primary")

    if submitted:
        try:
            record = OwnerFinanceProperty(
                status=PropertyStatus.DRAFT,
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                county=county,
                bedrooms=bedrooms,
                bathrooms=Decimal(str(bathrooms)),
                total_price=Decimal(total_price.replace(",", "").replace("$", "")),
                down_payment=Decimal(down_payment.replace(",", "").replace("$", "")),
                monthly_payment=Decimal(monthly_payment.replace(",", "").replace("$", "")),
                condition_summary=condition,
                repairs_needed=repairs,
                showing_instructions=showing,
                public_disclosures=disclosures,
                photo_urls=[line.strip() for line in photo_text.splitlines() if line.strip()],
                application_url=application_url or None,
            )
            plan = build_launch_plan(record)
            record.status = PropertyStatus.READY if plan.can_launch else PropertyStatus.NEEDS_INFORMATION
            save_property(record)
            if plan.can_launch:
                st.success("Property saved and ready for campaign generation.")
            else:
                st.warning("Property saved, but launch is blocked until the listed issues are fixed.")
                for error in plan.validation.errors:
                    st.write(f"- {error}")
        except (ValidationError, InvalidOperation, StorageError) as exc:
            st.error(f"Property could not be saved: {exc}")

elif page == "Record Manager":
    render_record_manager(storage)

elif page == "Campaign Readiness":
    st.subheader("Approve & Launch Everywhere — Readiness Preview")
    options = property_options()
    if not options:
        st.info("Add a property before building a campaign.")
        st.stop()
    selected_name = st.selectbox("Choose property", list(options))
    selected = options[selected_name]
    plan = build_launch_plan(selected)
    draft = build_deterministic_campaign_draft(selected)

    if plan.can_launch:
        st.success("Property facts passed the launch gate.")
    else:
        st.error("Launch blocked. Fix these items first:")
        for error in plan.validation.errors:
            st.write(f"- {error}")
    for warning in plan.validation.warnings:
        st.warning(warning)

    tracked_dwelyx_link = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium="property_campaign",
        property_id=selected.property_id,
    )
    st.write("### Buyer destination links")
    st.text_input("Tracked Dwelyx marketplace link", value=tracked_dwelyx_link)
    st.link_button("Open Dwelyx Marketplace", tracked_dwelyx_link, type="primary")
    st.markdown(f"[Open this property's featured landing page]({public_property_path(selected.property_id)})")
    st.markdown(f"[Open the featured-homes portal]({public_portal_path()})")
    st.caption("All buyer calls to action should lead into Dwelyx so buyers can browse the full inventory.")

    st.write("### Safe campaign preview")
    st.text_input("Headline", value=draft.headline)
    st.text_area("Short description", value=draft.short_description, height=120)
    st.text_area("Marketplace description", value=draft.marketplace_description, height=240)
    st.text_input("Email subject", value=draft.email_subject)
    st.text_area("SMS", value=draft.sms_message, height=80)

    launch_rows = [
        {"Channel": item.channel.name, "Mode": item.channel.mode, "State": item.state, "Reason": item.reason}
        for item in plan.items
    ]
    st.write("### Channel launch plan")
    st.dataframe(pd.DataFrame(launch_rows), use_container_width=True, hide_index=True)
    st.button("Approve & Launch Everywhere", disabled=True, help="Enabled after publishing adapters and approval records are built.")

elif page == "Dwelyx Traffic Hub":
    st.subheader("Dwelyx Traffic Hub")
    st.success("All buyer traffic is directed to Dwelyx, where buyers can browse the full owner-finance inventory.")
    st.link_button("Open Dwelyx", dwelyx_url, type="primary")

    st.write("### Build a tracked marketing link")
    left, right = st.columns(2)
    source = left.selectbox(
        "Lead source",
        [
            "Facebook Marketplace",
            "Facebook Groups",
            "Google",
            "Signs and QR Codes",
            "Email",
            "SMS",
            "Website",
            "Classifieds",
            "Other",
        ],
    )
    campaign = right.text_input("Campaign name", value="owner_finance_homes")

    options = {"All Dwelyx inventory": None, **property_options()}
    selected_name = st.selectbox("Property that generated the interest — optional", list(options))
    selected_property = options[selected_name]
    tracked_url = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium=source,
        campaign=campaign,
        property_id=selected_property.property_id if selected_property else None,
    )
    st.text_input("Copy this tracked Dwelyx link", value=tracked_url)
    st.link_button("Test This Dwelyx Link", tracked_url)
    st.caption("Use this link in the ad, text, email, QR code, sign, or social post. Dwelyx remains the buyer marketplace and buyer database.")

elif page == "Marketplace Guard":
    st.subheader("Facebook Marketplace Compliance Guard")
    options = property_options()
    if not options:
        st.info("Add a property before preparing Marketplace copy.")
        st.stop()
    selected_name = st.selectbox("Choose property", list(options), key="marketplace_property")
    selected = options[selected_name]
    draft = build_deterministic_campaign_draft(selected)
    used = st.number_input("Marketplace listings already used this month", min_value=0, max_value=50, value=0)
    title = st.text_input("Marketplace title", value=draft.headline)
    description = st.text_area("Marketplace description", value=draft.marketplace_description, height=280)
    check = review_marketplace_copy(selected, title, description, used)
    if check.passed:
        st.success("Marketplace package passed the configured compliance checks.")
    else:
        st.error("Do not publish until these items are corrected:")
        for error in check.errors:
            st.write(f"- {error}")
    for warning in check.warnings:
        st.warning(warning)
    st.link_button(
        "Buyer Call to Action — Browse Dwelyx",
        build_dwelyx_url(dwelyx_url, source="credit_friendly_homes", medium="facebook_marketplace", property_id=selected.property_id),
        type="primary",
    )
    st.caption("Final Marketplace publication remains manual. This guard reduces preventable errors but cannot guarantee platform approval.")

elif page == "System Setup":
    st.subheader("System Setup")
    st.write("### Security")
    st.success("App password is configured.")
    st.write("### Storage")
    if settings.configured:
        st.success("Supabase credentials are configured in Streamlit Secrets.")
        st.write("Private records and public property photos are connected.")
    else:
        st.warning("Supabase is not connected. The app is using fictional demo data stored only in memory.")

    st.write("### Dwelyx buyer destination")
    st.success(f"All buyer traffic points to {dwelyx_url}")
    st.caption("DWELYX_URL can be added to Streamlit Secrets later if the destination changes.")

    st.write("### Required Streamlit Secrets")
    st.code(
        'APP_PASSWORD = "your-private-password"\n'
        'SUPABASE_URL = "https://your-project.supabase.co"\n'
        'SUPABASE_SECRET_KEY = "sb_secret_..."'
    )
    st.info("Never paste these values into GitHub, chat screenshots, property notes, or public pages.")

else:
    st.subheader("Build Roadmap")
    roadmap = [
        "PR 1 — Foundation, property intake, launch validation, 14-channel registry, buyer matching, Marketplace Guard",
        "PR 2 — Streamlit deployment package fix",
        "PR 3 — Password gate and Supabase property/buyer storage",
        "PR 4 — Edit and delete property/buyer records",
        "PR 5 — Direct property photo upload and storage",
        "PR 6 — Automatic Supabase photo-bucket setup",
        "PR 7 — Public property landing pages and featured-homes portal",
        "PR 8 — Dwelyx buyer routing and tracked traffic-link hub",
        "PR 9 — Dwelyx click analytics and source reporting",
        "PR 10 — OpenAI campaign factory with structured outputs and fact guard",
        "PR 11 — Blog bot: 3 useful posts weekly, review mode, SEO linking, duplicate protection",
        "PR 12 — Email, SMS, referral, and buyer-reactivation traffic automation",
        "PR 13 — Marketplace/Facebook-group/classified assisted posting center",
        "PR 14 — Social, paid ads, analytics, shutdown controls, permissions, and audit logs",
    ]
    for item in roadmap:
        st.write(item)
