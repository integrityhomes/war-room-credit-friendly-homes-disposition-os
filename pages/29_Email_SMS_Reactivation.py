from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_tracking import build_channel_links
from cfh_disposition.channels import CHANNELS_BY_KEY
from cfh_disposition.dwelyx import dwelyx_base_url, tracking_app_base_url
from cfh_disposition.email_handoff import (
    EmailHandoffError,
    EmailHandoffSettings,
    dispatch_email_handoff,
)
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

st.set_page_config(page_title="Buyer Outreach", page_icon="✉️", layout="wide")


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


def email_buyer_label(buyer) -> str:
    name = " ".join(part for part in [buyer.first_name, buyer.last_name] if part).strip()
    return f"{name or 'Buyer'} — {buyer.email}"


require_password()
st.title("Buyer Outreach")
st.caption("Choose a marketable property, review the prepared email/text/reactivation message, and use an approved sender only when the buyer has saved consent.")
with st.expander("How outreach stays safe and trackable", expanded=False):
    st.write(
        "Property facts are read-only here. Price, down payment, monthly payment, bedrooms, and availability come from the saved property record."
    )
    st.write(
        "Email can use only the configured approved email sender handoff. SMS can use only the configured REI BlackBook / Profit Dial handoff."
    )
    st.write(
        "A successful handoff confirms only that the approved sender workflow accepted the request; it does not claim inbox or carrier delivery."
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
    st.warning("No property is currently Ready to Launch or Marketing Live for buyer outreach.")
    left, right = st.columns(2)
    if left.button("Open Marketing Home", type="primary", use_container_width=True):
        st.switch_page("pages/90_CFH_Marketing_Dispo.py")
    if right.button("Review Properties & Buyers", use_container_width=True):
        st.switch_page("pages/01_Record_Manager.py")
    st.stop()

options = {(item.display_address or str(item.property_id)): item for item in properties}
selected = options[st.selectbox("Property", list(options))]
default_campaign = f"buyer_outreach_{selected.city}_{selected.state}_{str(selected.property_id)[:8]}".lower()
with st.expander("Campaign tracking details", expanded=False):
    campaign = st.text_input(
        "Campaign name",
        value=default_campaign,
        help="This internal tracking name keeps buyer responses attributable to the property and outreach channel.",
    ).strip()
if not campaign:
    st.warning("A campaign tracking name is required before preparing outreach.")
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

        st.write("### Prepared message")
        st.write("**Subject / label**")
        st.code(package.subject, language=None)

        st.write("**Message options**")
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

        with st.expander("Tracking & sending guardrails", expanded=False):
            st.write("**Tracked buyer link**")
            st.text_input(
                "Exact tracked link",
                value=package.tracked_link,
                key=f"{key}_tracked_link",
                disabled=True,
            )
            st.caption(
                "Keep this exact link so downstream buyer activity stays attributable to this property, campaign, and outreach channel."
            )
            st.write("**Sending guardrails**")
            for note in package.compliance_notes:
                st.write(f"- {note}")

        if key == "email":
            st.divider()
            st.write("### Send Email")
            email_settings = EmailHandoffSettings.from_mapping(st.secrets)
            if email_settings.configured:
                st.success("Approved email sender is connected.")
            else:
                st.warning(
                    "Email sending is not connected yet. The approved sender endpoint must be configured before this page can hand off an email."
                )

            eligible_email_buyers = [
                buyer
                for buyer in buyers
                if buyer.email.strip() and buyer.email_consent and not buyer.do_not_contact
            ]
            if not eligible_email_buyers:
                st.info(
                    "No saved buyer currently has an email address, saved email consent, and an active contact status."
                )
            else:
                email_buyer_options = {
                    email_buyer_label(buyer): buyer for buyer in eligible_email_buyers
                }
                selected_email_buyer_label = st.selectbox(
                    "Buyer with saved email consent",
                    list(email_buyer_options),
                    key="email_sender_buyer",
                )
                selected_email_buyer = email_buyer_options[selected_email_buyer_label]
                email_variation_number = st.selectbox(
                    "Message variation",
                    list(range(1, len(package.message_variants) + 1)),
                    format_func=lambda value: f"Variation {value}",
                    key="email_sender_variation",
                )
                chosen_email_message = package.message_variants[email_variation_number - 1]
                st.text_input(
                    "Exact subject to send",
                    value=package.subject,
                    disabled=True,
                    key="email_sender_locked_subject",
                )
                st.text_area(
                    "Exact message to send",
                    value=chosen_email_message,
                    height=160,
                    disabled=True,
                    key="email_sender_locked_message",
                )
                email_requested_by = st.text_input(
                    "Requested by",
                    value="Sabrina",
                    key="email_sender_requested_by",
                )
                email_confirmed = st.checkbox(
                    "I confirm this buyer has saved email consent and I want the approved CFH email sender workflow to send this exact locked message.",
                    key="email_sender_confirm",
                )
                email_send_clicked = st.button(
                    "Send via Approved Email Sender",
                    type="primary",
                    use_container_width=True,
                    disabled=not email_settings.configured or not email_confirmed,
                )
                if email_send_clicked:
                    try:
                        receipt = dispatch_email_handoff(
                            st.secrets,
                            buyer=selected_email_buyer,
                            property_record=selected,
                            campaign=campaign,
                            subject=package.subject,
                            message=chosen_email_message,
                            tracked_link=package.tracked_link,
                            requested_by=email_requested_by,
                        )
                        st.success(
                            f"Email sender handoff accepted (HTTP {receipt.status_code}). "
                            "This confirms the handoff only; it does not claim inbox delivery."
                        )
                    except EmailHandoffError as exc:
                        record_operational_failure(
                            st.secrets,
                            CriticalFailureType.EMAIL,
                            summary=f"Email sender handoff failed for {selected.display_address}.",
                            technical_detail=str(exc),
                            property_id=str(selected.property_id),
                            property_address=selected.display_address,
                            channel="email",
                            campaign=campaign,
                            source="approved_email_sender",
                            buyer_id=str(selected_email_buyer.buyer_id),
                        )
                        st.error(
                            f"Email handoff failed and was sent to the main critical-failure ledger: {exc}"
                        )

        if key == "sms":
            st.divider()
            st.write("### Send Text Message")
            sms_settings = SmsHandoffSettings.from_mapping(st.secrets)
            if sms_settings.configured:
                st.success("REI BlackBook / Profit Dial SMS handoff is connected.")
            else:
                st.warning(
                    "SMS sending is not connected yet. The approved REI BlackBook / Profit Dial handoff must be configured before this page can send."
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
                    "Message variation",
                    list(range(1, len(package.message_variants) + 1)),
                    format_func=lambda value: f"Variation {value}",
                    key="profit_dial_variation",
                )
                chosen_message = package.message_variants[variation_number - 1]
                st.text_area(
                    "Exact message to send",
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
        "Download Buyer Outreach Package",
        data=csv_bytes,
        file_name=f"{campaign}_buyer_outreach.csv",
        mime="text/csv",
    )

st.warning(
    "Before sending, verify the property remains Ready to Launch or Marketing Live and confirm the buyer's saved consent for the selected channel. Change property facts only in Properties & Buyers."
)
