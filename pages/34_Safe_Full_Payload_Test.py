from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from cfh_disposition.ai_campaign import CampaignPackage, build_fallback_campaign
from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.automatic_launch import (
    AutomationDispatchSettings,
    build_automatic_launch_payload,
)
from cfh_disposition.buyer_handoff import enrich_launch_payload_with_buyer_audience
from cfh_disposition.buyer_intent import BuyerIntentError, BuyerIntentStore, build_match_queue
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.launch_plan import build_launch_plan
from cfh_disposition.safe_payload_test import (
    build_safe_full_payload_test_payload,
    dispatch_safe_full_payload_test,
    safe_payload_sample_json,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(page_title="Safe Full Payload Test", page_icon="🧪", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Safe Full Payload Test")
    st.caption("Private internal access")
    with st.form("safe_full_payload_login"):
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
st.title("Safe Full Payload Test")
st.caption(
    "Send the complete property and 15-channel campaign package to Zapier for inspection without giving the Zap any executable channel rows."
)
st.success(
    "Safety lock: this test sends zero executable top-level channels and explicitly disables publishing, email, SMS, ads, and spending."
)

settings = AutomationDispatchSettings.from_mapping(st.secrets)
if not settings.configured:
    st.error("AUTOMATION_WEBHOOK_URL is not configured in Streamlit Secrets.")
    st.stop()

try:
    storage = get_storage()
    properties = storage.list_properties()
    buyers = storage.list_buyers()
except StorageError as exc:
    st.error(f"Property or buyer storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("No saved property is available for testing.")
    st.stop()

options = {item.display_address or str(item.property_id): item for item in properties}
selected_label = st.selectbox("Property", list(options))
selected = options[selected_label]
plan = build_launch_plan(selected)
if not plan.can_launch:
    st.error("This property is not launch ready. Fix its blocking property facts first.")
    for error in plan.validation.errors:
        st.write(f"- {error}")
    st.stop()

campaign = st.text_input("Campaign name", value="owner_finance_homes").strip() or "owner_finance_homes"
requested_by = st.text_input("Test requested by", value="Shawn")

links = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
links_by_key = {row["Channel key"]: row for row in links}
base_link = links_by_key["property_page"]["Tracked Dwelyx link"]

campaign_key = f"campaign_package_{selected.property_id}"
package_data = st.session_state.get(campaign_key)
package = (
    CampaignPackage.model_validate(package_data)
    if package_data
    else build_fallback_campaign(selected, base_link)
)

buyer_matches = []
buyer_audience_error = ""
try:
    intent_ledger = BuyerIntentStore(st.secrets).load()
    buyer_matches = build_match_queue(
        buyers,
        [selected],
        intent_ledger,
        dwelyx_base_url(st.secrets),
        minimum_score=35,
    )
except BuyerIntentError as exc:
    buyer_audience_error = str(exc)

full_payload = build_automatic_launch_payload(
    selected,
    package,
    links_by_key,
    campaign=campaign,
    approved_by=requested_by,
    approved_at=datetime.now(UTC),
)
full_payload = enrich_launch_payload_with_buyer_audience(full_payload, buyer_matches)
safe_payload = build_safe_full_payload_test_payload(
    full_payload,
    requested_by=requested_by,
)

email_count = full_payload["buyer_audience"]["email_recipient_count"]
sms_count = full_payload["buyer_audience"]["sms_recipient_count"]
metrics = st.columns(6)
metrics[0].metric("Full payload channels", len(full_payload["channels"]))
metrics[1].metric("Executable test channels", len(safe_payload["channels"]))
metrics[2].metric("Matched email buyers", email_count)
metrics[3].metric("Matched SMS buyers", sms_count)
metrics[4].metric("Email allowed", "No")
metrics[5].metric("Ad spending allowed", "No")

if buyer_audience_error:
    st.warning(
        "The buyer-intent ledger could not be read, so this test contains no buyer recipients. "
        f"Reason: {buyer_audience_error}"
    )
elif not buyer_matches:
    st.warning(
        "No consent-ready buyers matched this property. Zapier will receive empty email/SMS recipient lists."
    )
else:
    st.success(
        f"Buyer handoff is populated: {email_count} consent-ready email recipient(s) and "
        f"{sms_count} consent-ready phone recipient(s)."
    )

with st.expander("Preview exactly what Zapier will receive"):
    st.code(safe_payload_sample_json(safe_payload), language="json")

st.warning(
    "This is a payload-inspection test only. It does not change campaign status in Supabase and does not mark any channel Posted or Scheduled."
)

if st.button("Send Safe Full Payload Test to Zapier", type="primary"):
    try:
        with st.spinner("Sending the non-executable full payload to Zapier..."):
            receipt = dispatch_safe_full_payload_test(safe_payload, settings)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.success(
            f"Safe full payload reached Zapier — HTTP {receipt.status_code}. No executable channel rows were sent."
        )
        if receipt.response_text:
            st.caption(f"Webhook response: {receipt.response_text}")
        st.info(
            "Now open Zapier Test Zap / Zap runs and select the newest request. Confirm event = "
            "credit_friendly_homes.campaign.full_payload_test, inspect full_campaign_payload, and "
            "confirm email.recipients / sms.recipients contain the consent-ready buyer contacts."
        )
