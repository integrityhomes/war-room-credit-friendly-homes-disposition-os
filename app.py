from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from cfh_disposition.ai_campaign import (
    CampaignFactoryError,
    CampaignFactorySettings,
    CampaignPackage,
    build_fallback_campaign,
    generate_ai_campaign,
)
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.campaign_launch import (
    CampaignLaunchStore,
    LaunchStoreError,
    render_campaign_launch_center,
)
from cfh_disposition.channels import CHANNELS
from cfh_disposition.dwelyx import build_dwelyx_url, dwelyx_base_url
from cfh_disposition.fact_lock import MARKETABLE_PROPERTY_STATUSES
from cfh_disposition.launch_plan import build_launch_plan
from cfh_disposition.marketplace_ui import render_marketplace_guard
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.operational_failures import render_critical_failure_banner
from cfh_disposition.public_pages import (
    public_portal_path,
    public_property_path,
    render_public_request,
)
from cfh_disposition.record_manager import render_record_manager
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.simple_flow import (
    MORE_TOOL_OPTIONS,
    PRIMARY_NAVIGATION,
    SimpleFlowStatus,
    build_simple_marketing_flow,
)
from cfh_disposition.storage import StorageError, SupabaseSettings, build_storage

st.set_page_config(
    page_title="Credit Friendly Homes Disposition OS",
    page_icon="🏠",
    layout="wide",
)


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
    return {
        item.display_address or str(item.property_id): item
        for item in st.session_state.properties
    }


def marketing_property_options() -> dict[str, OwnerFinanceProperty]:
    return {
        item.display_address or str(item.property_id): item
        for item in st.session_state.properties
        if item.status in MARKETABLE_PROPERTY_STATUSES
    }


def save_property(record: OwnerFinanceProperty) -> None:
    storage = get_storage()
    storage.save_property(record)
    current = {str(item.property_id): item for item in st.session_state.properties}
    current[str(record.property_id)] = record
    st.session_state.properties = list(current.values())


def navigate(page_name: str, *, property_label: str = "") -> None:
    if page_name == "More Tools":
        st.session_state.advanced_tool = "Record Manager"
    if property_label and page_name == "Campaign Readiness":
        st.session_state.campaign_readiness_property = property_label
    if property_label and page_name == "Campaign Launch Center":
        st.session_state.launch_center_property = property_label
    # Streamlit does not allow changing a widget-backed session-state key
    # after that widget has been created in the current run. Queue the
    # destination and apply it before the sidebar radio is instantiated.
    st.session_state.pending_main_navigation = page_name
    st.rerun()


def load_launch_state(property_id: str):
    try:
        store = CampaignLaunchStore(st.secrets)
        return store.load(property_id, "owner_finance_homes"), ""
    except LaunchStoreError as exc:
        return None, str(exc)


def render_flow_step(step, column) -> None:
    with column.container(border=True):
        st.write(f"### {step.number}. {step.title}")
        if step.status == SimpleFlowStatus.COMPLETE:
            st.success(step.status.value)
        elif step.status == SimpleFlowStatus.ACTION_REQUIRED:
            st.warning(step.status.value)
        else:
            st.error(step.status.value)
        st.write(step.detail)


def render_simple_marketing_flow() -> None:
    st.subheader(f"Simple {len(CHANNELS)}-Channel Marketing Flow")
    st.caption("Choose the property, prepare the campaign, and launch the marketing. That is the full operating path.")

    options = property_options()
    if not options:
        flow = build_simple_marketing_flow([])
        columns = st.columns(3)
        for step, column in zip(flow.steps, columns, strict=True):
            render_flow_step(step, column)
        st.info("Next action: add the first property.")
        if st.button("Add Property", type="primary"):
            navigate("Property Intake")
        return

    selected_label = st.selectbox(
        "Property",
        list(options),
        key="simple_flow_property",
    )
    selected = options[selected_label]
    st.session_state.active_marketing_property_id = str(selected.property_id)

    launch_state, launch_error = load_launch_state(str(selected.property_id))
    flow = build_simple_marketing_flow(
        st.session_state.properties,
        selected_property_id=str(selected.property_id),
        launch_state=launch_state,
    )

    terms = st.columns(4)
    terms[0].metric("Property", selected.display_address)
    terms[1].metric("Down Payment", money(selected.down_payment))
    terms[2].metric("Monthly Payment", money(selected.monthly_payment))
    terms[3].metric("Channels Launched", f"{flow.launched_channels} of {flow.total_channels}")

    columns = st.columns(3)
    for step, column in zip(flow.steps, columns, strict=True):
        render_flow_step(step, column)

    if flow.complete:
        st.success("The property, campaign, and all 15 property marketing channels are in place.")
    else:
        st.info(f"Next action: {flow.next_step.detail}")

    if st.button(flow.next_step.button_label, type="primary"):
        navigate(flow.next_step.destination, property_label=selected_label)

    if launch_error:
        st.caption("Detailed launch records could not be read. Open System Setup only if the launch count looks incorrect.")

    with st.expander("Detailed marketing tools"):
        st.page_link(
            "pages/24_15_Channel_Campaign_Cadence_Refresh.py",
            label="Open 15-Channel Refresh Center",
        )
        st.page_link(
            "pages/19_Dwelyx_Results_Attribution.py",
            label="Open Dwelyx Results",
        )
        st.page_link(
            "pages/23_Daily_Executive_Disposition_Command.py",
            label="Open Executive Command Center",
        )


def render_property_intake(settings: SupabaseSettings) -> None:
    st.subheader("Step 1 — Add an Owner-Finance Property")
    st.info("This central property record is the only place price, down payment, monthly payment, bedrooms, and availability may be changed. Downstream marketing is read-only and must regenerate from this record.")
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
        bathrooms = left.number_input(
            "Bathrooms*",
            min_value=0.0,
            max_value=20.0,
            value=1.0,
            step=0.5,
        )
        total_price = middle.text_input("Total price*", value="100000")
        down_payment = right.text_input("Down payment*", value="5000")
        monthly_payment = left.text_input("Monthly payment*", value="1200")
        available_date = middle.text_input("Available date", placeholder="YYYY-MM-DD or Available now")
        condition = st.text_area("Condition summary*")
        repairs = st.text_area("Known repairs needed")
        showing = st.text_area("Showing instructions*")
        disclosures = st.text_area("Public disclosures*")
        photo_text = st.text_area("Photo URLs* — one per line")
        application_url = st.text_input("Dwelyx property listing URL — optional")
        submitted = st.form_submit_button("Validate and Save Property", type="primary")

    if not submitted:
        return

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
            available_date=available_date,
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
        st.session_state.simple_flow_property = record.display_address
        if plan.can_launch:
            st.success("Property saved and ready for campaign preparation.")
            if st.button("Continue to Campaign", type="primary"):
                navigate("Campaign Readiness", property_label=record.display_address)
        else:
            st.warning("Property saved, but the blocking items must be fixed before marketing.")
            for error in plan.validation.errors:
                st.write(f"- {error}")
    except (ValidationError, InvalidOperation, StorageError) as exc:
        st.error(f"Property could not be saved: {exc}")


def render_campaign_readiness(
    dwelyx_url: str,
    campaign_settings: CampaignFactorySettings,
) -> None:
    st.subheader("Step 2 — Prepare the Marketing Campaign")
    options = marketing_property_options()
    if not options:
        st.info("No Ready to Launch or Marketing Live property is available for campaign preparation.")
        if st.button("Add Property", type="primary"):
            navigate("Property Intake")
        return

    saved_selection = st.session_state.get("campaign_readiness_property")
    if saved_selection not in options:
        st.session_state.campaign_readiness_property = next(iter(options))
    selected_name = st.selectbox(
        "Property",
        list(options),
        key="campaign_readiness_property",
    )
    selected = options[selected_name]
    plan = build_launch_plan(selected)

    if plan.can_launch:
        st.success("Property facts passed the marketing readiness check.")
    else:
        st.error("Marketing is blocked. Fix these items in More Tools → Record Manager:")
        for error in plan.validation.errors:
            st.write(f"- {error}")
        if st.button("Open Record Manager", type="primary"):
            navigate("More Tools")
        return

    for warning in plan.validation.warnings:
        st.warning(warning)

    tracked_dwelyx_link = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium="property_campaign",
        campaign="owner_finance_home",
        property_id=selected.property_id,
    )
    campaign_key = f"campaign_package_{selected.property_id}"
    campaign_mode_key = f"campaign_mode_{selected.property_id}"
    fallback_package = build_fallback_campaign(selected, tracked_dwelyx_link)

    if campaign_settings.configured:
        st.info(f"AI campaign writer is connected using {campaign_settings.model}.")
        if st.button("Generate Fresh Campaign Package", type="primary"):
            try:
                with st.spinner("Creating and checking the 15-channel property campaign..."):
                    package = generate_ai_campaign(selected, tracked_dwelyx_link, campaign_settings)
                st.session_state[campaign_key] = package.model_dump(mode="json")
                st.session_state[campaign_mode_key] = "AI generated — fact guard passed"
                st.success("Campaign generated and passed the fact guard.")
            except CampaignFactoryError as exc:
                st.error(str(exc))
                st.warning("The safe campaign template remains available.")
    else:
        st.info("The safe campaign template is ready. OpenAI is optional.")

    package_data = st.session_state.get(campaign_key)
    package = CampaignPackage.model_validate(package_data) if package_data else fallback_package
    mode = st.session_state.get(campaign_mode_key, "Safe template")
    st.success(f"Campaign package ready: {mode}")
    st.caption("Campaign copy is read-only. Change locked facts only in the central property record, then regenerate the campaign.")

    with st.expander("Review detailed campaign copy"):
        for index, (label, text) in enumerate(package.channel_rows()):
            height = 90 if label in {"Headline", "Email Subject", "SMS", "Dwelyx Call to Action"} else 180
            st.text_area(
                label,
                value=text,
                height=height,
                key=f"campaign_{selected.property_id}_{index}",
                disabled=True,
            )

    with st.expander("Review buyer links and channel plan"):
        st.text_input("Tracked Dwelyx buyer link", value=tracked_dwelyx_link, disabled=True)
        st.link_button("Open Dwelyx Buyer Registration", tracked_dwelyx_link)
        st.markdown(f"[Open property landing page]({public_property_path(selected.property_id)})")
        st.markdown(f"[Open all featured homes]({public_portal_path()})")
        launch_rows = [
            {
                "Channel": item.channel.name,
                "Mode": item.channel.mode,
                "State": item.state,
                "Reason": item.reason,
            }
            for item in plan.items
        ]
        st.dataframe(pd.DataFrame(launch_rows), use_container_width=True, hide_index=True)

    if st.button(f"Continue to {len(CHANNELS)}-Channel Launch", type="primary"):
        navigate("Campaign Launch Center", property_label=selected_name)


def render_dwelyx_traffic_hub(dwelyx_url: str) -> None:
    st.write("### Dwelyx Traffic Hub")
    st.link_button("Open Dwelyx", dwelyx_url, type="primary")
    left, right = st.columns(2)
    source = left.selectbox(
        "Lead source",
        [
            "Facebook Groups",
            "Nextdoor",
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
    options = {"All Dwelyx inventory": None, **marketing_property_options()}
    selected_name = st.selectbox("Property that generated the interest — optional", list(options))
    selected_property = options[selected_name]
    tracked_url = build_dwelyx_url(
        dwelyx_url,
        source="credit_friendly_homes",
        medium=source,
        campaign=campaign,
        property_id=selected_property.property_id if selected_property else None,
    )
    st.text_input("Copy this tracked Dwelyx link", value=tracked_url, disabled=True)
    st.caption("Do not paste direct external links into Facebook Marketplace listings.")


def render_more_tools(storage, dwelyx_url: str) -> None:
    st.subheader("More Tools")
    tool = st.selectbox("Choose a tool", MORE_TOOL_OPTIONS, key="advanced_tool")
    if tool == "Record Manager":
        render_record_manager(storage)
    elif tool == "Dwelyx Traffic Hub":
        render_dwelyx_traffic_hub(dwelyx_url)
    else:
        render_marketplace_guard(st.session_state.properties, st.secrets)

    st.divider()
    st.write("### Detailed dashboards")
    links = st.columns(3)
    with links[0]:
        st.page_link(
            "pages/24_15_Channel_Campaign_Cadence_Refresh.py",
            label="15-Channel Refresh",
        )
    with links[1]:
        st.page_link(
            "pages/19_Dwelyx_Results_Attribution.py",
            label="Dwelyx Results",
        )
    with links[2]:
        st.page_link(
            "pages/23_Daily_Executive_Disposition_Command.py",
            label="Executive Command",
        )


def render_system_setup(
    settings: SupabaseSettings,
    campaign_settings: CampaignFactorySettings,
    dwelyx_url: str,
) -> None:
    st.subheader("System Setup")
    st.success("App password is configured.")
    if settings.configured:
        st.success("Supabase storage is connected.")
    else:
        st.warning("Supabase is not connected. The app is using fictional demo data in memory.")
    st.success(f"Supported buyer traffic points to {dwelyx_url}")
    if campaign_settings.configured:
        st.success(f"OpenAI is connected using {campaign_settings.model}.")
    else:
        st.info("OpenAI is optional. Campaigns currently use safe template mode.")
    with st.expander("Streamlit Secrets"):
        st.code(
            'APP_PASSWORD = "your-private-password"\n'
            'SUPABASE_URL = "https://your-project.supabase.co"\n'
            'SUPABASE_SECRET_KEY = "sb_secret_..."\n'
            'OPENAI_API_KEY = "sk-..."\n'
            'OPENAI_MODEL = "gpt-5-mini"  # optional'
        )
        st.warning("Never paste secrets into GitHub, screenshots, property notes, or public pages.")


storage = get_storage()
if render_public_request(storage):
    st.stop()

require_password()
load_records()

st.title("Credit Friendly Homes Disposition OS")
st.caption("Simple property marketing across 15 property channels plus buyer-acquisition channels, with supported buyer paths leading to Dwelyx.")

storage = get_storage()
settings = SupabaseSettings.from_mapping(st.secrets)
dwelyx_url = dwelyx_base_url(st.secrets)
campaign_settings = CampaignFactorySettings.from_mapping(st.secrets)

st.sidebar.success(f"Storage: {storage.mode}")
if st.sidebar.button("Refresh saved records"):
    load_records(force=True)
    st.rerun()
if st.sidebar.button("Log out"):
    st.session_state.authenticated = False
    st.rerun()

pending_navigation = st.session_state.pop("pending_main_navigation", None)
if pending_navigation in PRIMARY_NAVIGATION:
    st.session_state.main_navigation = pending_navigation
if st.session_state.get("main_navigation") not in PRIMARY_NAVIGATION:
    st.session_state.main_navigation = PRIMARY_NAVIGATION[0]
page = st.sidebar.radio(
    "Marketing Workflow",
    PRIMARY_NAVIGATION,
    key="main_navigation",
)
st.sidebar.caption("Use the first four screens for normal daily work. More Tools is optional.")

if st.session_state.get("storage_error"):
    st.error(st.session_state.storage_error)
    st.warning("Open System Setup and confirm the Supabase connection before entering records.")

render_critical_failure_banner(st.secrets)
st.divider()

if page == "Simple Marketing Flow":
    render_simple_marketing_flow()
elif page == "Property Intake":
    render_property_intake(settings)
elif page == "Campaign Readiness":
    render_campaign_readiness(dwelyx_url, campaign_settings)
elif page == "Campaign Launch Center":
    render_campaign_launch_center(st.session_state.properties, st.secrets, dwelyx_url)
elif page == "More Tools":
    render_more_tools(storage, dwelyx_url)
else:
    render_system_setup(settings, campaign_settings, dwelyx_url)
