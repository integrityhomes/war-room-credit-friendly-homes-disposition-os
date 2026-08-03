from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from cfh_disposition.channels import CHANNELS
from cfh_disposition.content import build_deterministic_campaign_draft
from cfh_disposition.dashboard import calculate_dashboard_metrics
from cfh_disposition.launch_plan import build_launch_plan
from cfh_disposition.marketplace import review_marketplace_copy
from cfh_disposition.matching import match_buyer_to_property
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES

st.set_page_config(page_title="Credit Friendly Homes Disposition OS", page_icon="🏠", layout="wide")

if "properties" not in st.session_state:
    st.session_state.properties = SAMPLE_PROPERTIES.copy()
if "buyers" not in st.session_state:
    st.session_state.buyers = SAMPLE_BUYERS.copy()


def money(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:,.0f}"


def property_options() -> dict[str, OwnerFinanceProperty]:
    return {item.display_address or str(item.property_id): item for item in st.session_state.properties}


st.title("Credit Friendly Homes Disposition OS")
st.caption("Owner-finance marketing, buyer growth, landing pages, compliance, and launch automation.")

page = st.sidebar.radio(
    "Navigation",
    ["Executive War Room", "Property Intake", "Campaign Readiness", "Buyer Growth", "Marketplace Guard", "Build Roadmap"],
)
st.sidebar.info("Public repository mode: never enter real API keys, passwords, or buyer records into GitHub.")

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
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.subheader("14-Channel Growth Plan")
    channel_rows = [{"Channel": item.name, "Mode": item.mode, "Purpose": item.purpose} for item in CHANNELS]
    st.dataframe(pd.DataFrame(channel_rows), use_container_width=True, hide_index=True)

elif page == "Property Intake":
    st.subheader("Add an Owner-Finance Property")
    st.write("This intake uses session memory for the first build. Supabase and Google Sheets are connected in later PRs.")
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
        submitted = st.form_submit_button("Validate and Add Property", type="primary")

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
            st.session_state.properties.append(record)
            if plan.can_launch:
                st.success("Property added and ready for campaign generation.")
            else:
                st.warning("Property added, but launch is blocked until the listed issues are fixed.")
                for error in plan.validation.errors:
                    st.write(f"- {error}")
        except (ValidationError, InvalidOperation) as exc:
            st.error(f"Property could not be added: {exc}")

elif page == "Campaign Readiness":
    st.subheader("Approve & Launch Everywhere — Readiness Preview")
    options = property_options()
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
    st.subheader("Buyer Matching Preview")
    options = property_options()
    selected_name = st.selectbox("Choose property", list(options), key="buyer_property")
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
    st.dataframe(pd.DataFrame(rows).sort_values("Score", ascending=False), use_container_width=True, hide_index=True)
    st.info("Future PRs add Supabase storage, lead forms, referral links, reactivation, and Call Now queues.")

elif page == "Marketplace Guard":
    st.subheader("Facebook Marketplace Compliance Guard")
    options = property_options()
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

else:
    st.subheader("Build Roadmap")
    roadmap = [
        "PR 1 — Foundation, property intake, launch validation, 14-channel registry, buyer matching, Marketplace Guard",
        "PR 2 — Supabase property and buyer database with safe migrations",
        "PR 3 — WordPress property landing pages and available-home portal",
        "PR 4 — OpenAI campaign factory with structured outputs and fact guard",
        "PR 5 — Blog bot: 3 useful posts weekly, review mode, SEO linking, duplicate protection",
        "PR 6 — Email, SMS, referral, and buyer-reactivation automation",
        "PR 7 — Marketplace/Facebook-group/classified assisted posting center",
        "PR 8 — Buyer qualification, Call Now queue, showing and application follow-up",
        "PR 9 — Instagram, TikTok, YouTube, Meta housing ads, and Google Ads adapters",
        "PR 10 — Analytics, optimization, sold-property shutdown, permissions, and audit logs",
    ]
    for item in roadmap:
        st.write(item)
