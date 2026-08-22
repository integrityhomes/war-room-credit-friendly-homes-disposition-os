from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.fact_lock import MARKETABLE_PROPERTY_STATUSES
from cfh_disposition.operational_failures import (
    CriticalFailureType,
    record_operational_failure,
)
from cfh_disposition.outreach_channels import OutreachPackageError, build_outreach_package
from cfh_disposition.rei_blackbook_sms import (
    ReiBlackBookSmsError,
    SmsHandoffSettings,
    dispatch_sms_handoff,
)
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(page_title="Email, SMS & Reactivation", page_icon="✉️", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    with st.form("outreach_login"):
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


def buyer_label(buyer) -> str:
    name = " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip()
    phone_tail = buyer.phone[-4:] if buyer.phone else "no phone"
    return f"{name or 'Buyer'} — ••••{phone_tail}"


require_password()
st.title("Matched Buyer Email + SMS + Reactivation")
st.caption("Prepare three separately tracked buyer-outreach channels from one saved property.")
st.info(
    "Fact-lock active: this page prepares read-only copy and attribution from the central property record. "
    "Price, down payment, monthly payment, bedrooms, and availability cannot be edited here. "
    "REI BlackBook / Profit Dial remains the actual SMS sender."
)

try:
    storage = get_storage()
    properties = [
        item
        for item in storage.list_properties()
        if item.status in MARKETABLE_PROPERTY_STATUSES
    ]
    buyers = storage.list_buyers()
except StorageError as exc:
    st.error(f"Marketing storage is unavailable: {exc}")
    st.stop()

if not properties:
    st.warning("No Ready to Launch or Marketing Live property is available for buyer outreach.")
    st.stop()

options = {(item.display_address or str(item.property_id)): item for item in properties}
selected = options[st.selectbox("Property", list(options))]
campaign = st.text_input(
    "Campaign name",
    value=f"buyer_outreach_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower(),
).strip()
if not campaign:
    st.warning("Enter a campaign name.")
    st.stop()

links = build_channel_links(
    dwelyx_base_url(st.secrets),
    campaign=campaign,
    property_id=selected.property_id,
    tracking_base_url=tracking_app_base_url(st.secrets),
)
links_by_key = {row["Channel key"]: row["Tracked Dwelyx link"] for row in links}

channel_keys = ("email", "sms", "reactivation")
tabs = st.tabs([CHANNELS_BY_KEY[key].name for key in channel_keys])
export_rows: list[dict[str, str]] = []

for tab, key in zip(tabs, channel_keys, strict=True):
    channel = CHANNELS_BY_KEY[key]
    with tab:
        try:
            package = build_outreach_package(
                selected,
                channel_key=key,
                channel_name=channel.name,
                tracked_link=links_by_key[key],
            )
        except OutreachPackageError as exc:
            st.error(f"Outreach guard blocked this package: {exc}")
            continue

        st.write("### Subject / Label")
        st.code(package.subject, language=None)

        st.write("### Locked message variations")
        for index, message in enumerate(package.message_variants, start=1):
            st.text_area(
                f"Variation {index}",
                value=message,
                height=130,
                key=f"{key}_outreach_{index}",
                disabled=True,
            )
            export_rows.append(
                {
                    "channel": channel.name,
                    "channel_key": key,
                    "campaign": campaign,
                    "property_id": str(selected.property_id),
                    "property": selected.display_address,
                    "variation": str(index),
                    "subject": package.subject,
                    "message": message,
                    "tracked_dwelyx_link": package.tracked_link,
                }
            )

        st.write("### Tracked Dwelyx link")
        st.text_input(
            "Exact tracked link",
            value=package.tracked_link,
            key=f"{key}_tracked_link",
            disabled=True,
        )
        st.caption(
            "Use this exact link so downstream registrations, applications, showings, contracts, and filled homes stay attributed to this property, campaign, and outreach channel."
        )

        st.write("### Sending guardrails")
        for note in package.compliance_notes:
            st.write(f"- {note}")

        if key == "sms":
            st.divider()
            st.write("### Send through REI BlackBook / Profit Dial")
            sms_settings = SmsHandoffSettings.from_mapping(st.secrets)
            if sms_settings.configured:
                st.success("SMS marketing handoff is connected to the configured Zapier webhook.")
            else:
                st.warning(
                    "SMS handoff is not connected yet. Add the real Zapier Catch Hook URL as "
                    "SMS_SENDER_WEBHOOK_URL in Streamlit Secrets. No alternate SMS provider will be used."
                )

            eligible_buyers = [
                buyer
                for buyer in buyers
                if buyer.phone.strip() and buyer.sms_consent and not buyer.do_not_contact
            ]
            if not eligible_buyers:
                st.info("No saved buyer currently has a phone number, SMS consent, and an active contact status.")
            else:
                buyer_options = {buyer_label(buyer): buyer for buyer in eligible_buyers}
                selected_buyer_label = st.selectbox(
                    "Buyer with saved SMS consent",
                    list(buyer_options),
                    key="profit_dial_buyer",
                )
                selected_buyer = buyer_options[selected_buyer_label]
                variation_number = st.selectbox(
                    "Locked SMS variation",
                    list(range(1, len(package.message_variants) + 1)),
                    format_func=lambda value: f"Variation {value}",
                    key="profit_dial_variation",
                )
                chosen_message = package.message_variants[variation_number - 1]
                st.text_area(
                    "Exact message that will be handed to Profit Dial",
                    value=chosen_message,
                    height=130,
                    disabled=True,
                    key="profit_dial_locked_message",
                )
                requested_by = st.text_input(
                    "Requested by",
                    value="Sabrina",
                    key="profit_dial_requested_by",
                )
                confirmed = st.checkbox(
                    "I confirm this buyer has saved SMS consent and I want REI BlackBook / Profit Dial to run the approved CFH marketing SMS workflow.",
                    key="profit_dial_confirm",
                )
                send_clicked = st.button(
                    "Send via REI BlackBook / Profit Dial",
                    type="primary",
                    use_container_width=True,
                    disabled=not sms_settings.configured or not confirmed,
                )
                if send_clicked:
                    try:
                        receipt = dispatch_sms_handoff(
                            st.secrets,
                            buyer=selected_buyer,
                            property_record=selected,
                            campaign=campaign,
                            message=chosen_message,
                            tracked_link=package.tracked_link,
                            requested_by=requested_by,
                        )
                        st.success(
                            f"REI BlackBook / Profit Dial handoff accepted (HTTP {receipt.status_code}). "
                            "This confirms the handoff only; it does not claim carrier delivery."
                        )
                    except ReiBlackBookSmsError as exc:
                        record_operational_failure(
                            st.secrets,
                            CriticalFailureType.SMS,
                            summary=f"Profit Dial SMS handoff failed for {selected.display_address}.",
                            technical_detail=str(exc),
                            property_id=str(selected.property_id),
                            property_address=selected.display_address,
                            channel="sms",
                            campaign=campaign,
                            source="rei_blackbook_profit_dial",
                            buyer_id=str(selected_buyer.buyer_id),
                        )
                        st.error(
                            f"SMS handoff failed and was sent to the main critical-failure ledger: {exc}"
                        )

if export_rows:
    csv_bytes = pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download locked email + SMS + reactivation package CSV",
        data=csv_bytes,
        file_name=f"{campaign}_buyer_outreach.csv",
        mime="text/csv",
    )

st.warning(
    "Before sending, verify the property remains Ready to Launch or Marketing Live and confirm the buyer's saved consent for the selected channel. Change property facts only in Record Manager."
)
