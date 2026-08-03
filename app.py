from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channels import CHANNELS
from cfh_disposition.content import build_deterministic_campaign_draft
from cfh_disposition.dashboard import calculate_dashboard_metrics
from cfh_disposition.launch_plan import build_launch_plan
from cfh_disposition.marketplace import review_marketplace_copy
from cfh_disposition.matching import match_buyer_to_property
from cfh_disposition.models import (
    BuyerProfile,
    CommunicationPreference,
    OwnerFinanceProperty,
    PropertyStatus,
)
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


def save_buyer(record: BuyerProfile) -> None:
    storage = get_storage()
    storage.save_buyer(record)
    current = {str(item.buyer_id): item for item in st.session_state.buyers}
    current[str(record.buyer_id)] = record
    st.session_state.buyers = list(current.values())


require_password()
load_records()

st.title("Credit Friendly Homes Disposition OS")
st.caption("Owner-finance marketing, buyer growth, landing pages, compliance, and launch automation.")

storage = get_storage()
settings = SupabaseSettings.from_mapping(st.secrets)
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
        "Campaign Readiness",
        "Buyer Growth",
        "Marketplace Guard",
        "System Setup",
        "Build Roadmap",
    ],
)
st.sidebar.info("Public repository mode: credentials and real records belong only in Streamlit Secrets and Supabase.")

if st.session_state.get("storage_error"):
    st.error(st.session_state.storage_error)
    st.warning("Open System Setup and confirm the Supabase migration and secrets before entering records.")

if page == "Executive War Room":
    metrics = calculate_dashboard_metrics(st.session_state.properties, st.session_state.buyers)
    columns = st.columns(6)
    values = [
        ("Properties", metrics.total_properties),
        ("Launch Ready", metrics.launch_ready),
        ("Marketing Live", metrics.live_properties),
        ("Needs Information", metrics.needs_information),
        ("Buyers", metrics.total_buyers),
        ("Eligible Matches", metrics.eligible_matches),
    ]
    for column, (label, value) in zip(columns, values, strict=True):
        column.metric(label, value)

    rows = []
    for item in st.session_state.properties:
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
        application_url = st.text_input("Application URL")
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

elif page == "Buyer Growth":
    st.subheader("Buyer Database and Matching")
    if not settings.configured:
        st.warning("Demo mode is active. Connect Supabase before entering real buyer information.")

    with st.expander("Add buyer", expanded=False):
        with st.form("buyer_intake"):
            left, right = st.columns(2)
            first_name = left.text_input("First name*")
            last_name = right.text_input("Last name")
            email = left.text_input("Email")
            phone = right.text_input("Phone")
            cities = left.text_input("Preferred cities — comma separated")
            states = right.text_input("Preferred states — comma separated")
            minimum_bedrooms = left.number_input("Minimum bedrooms", min_value=0, max_value=20, value=2)
            maximum_payment = right.text_input("Maximum monthly payment", value="1200")
            available_down = left.text_input("Available down payment", value="5000")
            move_days = right.number_input("Move timeframe in days", min_value=0, max_value=3650, value=60)
            preference = left.selectbox("Preferred contact", [item.value for item in CommunicationPreference])
            source = right.text_input("Buyer source", value="Website")
            email_consent = left.checkbox("Email consent")
            sms_consent = right.checkbox("SMS consent")
            call_consent = left.checkbox("Call consent")
            buyer_submitted = st.form_submit_button("Save Buyer", type="primary")

        if buyer_submitted:
            try:
                buyer = BuyerProfile(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=phone,
                    preferred_cities=[item.strip() for item in cities.split(",") if item.strip()],
                    preferred_states=[item.strip().upper() for item in states.split(",") if item.strip()],
                    minimum_bedrooms=minimum_bedrooms,
                    maximum_monthly_payment=Decimal(maximum_payment.replace(",", "").replace("$", "")),
                    available_down_payment=Decimal(available_down.replace(",", "").replace("$", "")),
                    move_timeframe_days=move_days,
                    communication_preference=CommunicationPreference(preference),
                    email_consent=email_consent,
                    sms_consent=sms_consent,
                    call_consent=call_consent,
                    source=source,
                )
                save_buyer(buyer)
                st.success("Buyer saved.")
            except (ValidationError, InvalidOperation, StorageError) as exc:
                st.error(f"Buyer could not be saved: {exc}")

    options = property_options()
    if not options:
        st.info("Add a property to preview buyer matching.")
        st.stop()
    selected_name = st.selectbox("Match buyers to property", list(options), key="buyer_property")
    selected = options[selected_name]
    rows = []
    for buyer in st.session_state.buyers:
        match = match_buyer_to_property(buyer, selected)
        rows.append(
            {
                "Buyer": f"{buyer.first_name} {buyer.last_name}".strip(),
                "Source": buyer.source,
                "Score": match.score,
                "Eligible": "Yes" if match.is_eligible else "No",
                "Reasons": "; ".join(match.reasons),
                "Disqualifiers": "; ".join(match.disqualifiers),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows).sort_values("Score", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("No buyers saved yet.")

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
    st.caption("Final Marketplace publication remains manual. This guard reduces preventable errors but cannot guarantee platform approval.")

elif page == "System Setup":
    st.subheader("System Setup")
    st.write("### Security")
    st.success("App password is configured.")
    st.write("### Storage")
    if settings.configured:
        st.success("Supabase credentials are configured in Streamlit Secrets.")
        st.write("Run the included SQL migration before saving real records.")
    else:
        st.warning("Supabase is not connected. The app is using fictional demo data stored only in memory.")

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
        "PR 4 — WordPress property landing pages and available-home portal",
        "PR 5 — OpenAI campaign factory with structured outputs and fact guard",
        "PR 6 — Blog bot: 3 useful posts weekly, review mode, SEO linking, duplicate protection",
        "PR 7 — Email, SMS, referral, and buyer-reactivation automation",
        "PR 8 — Marketplace/Facebook-group/classified assisted posting center",
        "PR 9 — Buyer qualification, Call Now queue, showing and application follow-up",
        "PR 10 — Social, paid ads, analytics, shutdown controls, permissions, and audit logs",
    ]
    for item in roadmap:
        st.write(item)
