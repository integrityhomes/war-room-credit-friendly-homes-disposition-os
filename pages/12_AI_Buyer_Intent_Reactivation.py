from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.buyer_intent import (
    BuyerIntentError,
    BuyerIntentStore,
    IntentTier,
    OutreachChannel,
    build_match_queue,
    match_rows,
    record_outreach,
    record_signal,
)
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="AI Buyer Intent & Reactivation",
    page_icon="🎯",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("AI Buyer Intent & Reactivation")
    st.caption("Private internal access")
    with st.form("buyer_intent_login"):
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
st.title("AI Buyer Intent & Reactivation Engine")
st.caption(
    "Ranks consented buyers against available owner-finance homes, prepares measured reactivation "
    "campaigns, and prevents repeated outreach inside the saved cooldown."
)

try:
    storage = get_storage()
    buyers = storage.list_buyers()
    properties = storage.list_properties()
    intent_store = BuyerIntentStore(st.secrets)
    ledger = intent_store.load()
except (StorageError, BuyerIntentError) as exc:
    st.error(f"Buyer Intent Engine is safety-locked: {exc}")
    st.stop()

queue_tab, signal_tab, history_tab = st.tabs(
    ["Match & Reactivate", "Record Engagement", "Outreach History"]
)

with queue_tab:
    if not buyers:
        st.info("Add buyer profiles before building a reactivation queue.")
    elif not properties:
        st.info("Add available properties before building a reactivation queue.")
    else:
        property_options = {
            item.display_address or str(item.property_id): item for item in properties
        }
        selected_properties = st.multiselect(
            "Properties to match",
            options=list(property_options),
            default=list(property_options),
        )
        minimum_score = st.slider("Minimum buyer-intent score", 0, 100, 35, 5)
        dwelyx_url = dwelyx_base_url(st.secrets)
        matches = build_match_queue(
            buyers,
            [property_options[name] for name in selected_properties],
            ledger,
            dwelyx_url,
            minimum_score=minimum_score,
        )

        hot = sum(match.tier == IntentTier.HOT for match in matches)
        warm = sum(match.tier == IntentTier.WARM for match in matches)
        metrics = st.columns(4)
        metrics[0].metric("Ready Matches", len(matches))
        metrics[1].metric("Hot Buyers", hot)
        metrics[2].metric("Warm Buyers", warm)
        metrics[3].metric(
            "Consent Ready",
            sum(match.email_allowed or match.sms_allowed for match in matches),
        )

        if not matches:
            st.warning(
                "No consented buyer/property match is ready at this score. Lower the score only after "
                "reviewing buyer fit; Do Not Contact and missing-consent buyers remain blocked."
            )
        else:
            st.dataframe(
                pd.DataFrame(match_rows(matches)),
                use_container_width=True,
                hide_index=True,
            )
            labels = {
                f"{match.score} — {match.buyer_name} → {match.property_address}": match
                for match in matches
            }
            selected_label = st.selectbox("Work one buyer match", list(labels))
            match = labels[selected_label]

            details = st.columns(4)
            details[0].metric("Intent", match.tier.value)
            details[1].metric("Score", match.score)
            details[2].metric("Email", "Ready" if match.email_allowed else "Blocked")
            details[3].metric("SMS", "Ready" if match.sms_allowed else "Blocked")
            st.write(f"**Why this buyer matched:** {', '.join(match.reasons)}")
            st.text_input("Tracked Dwelyx buyer link", value=match.tracked_link)

            email_tab, sms_tab = st.tabs(["Email Package", "SMS Package"])
            with email_tab:
                st.text_input("Email recipient", value=match.email)
                st.text_input("Email subject", value=match.email_subject)
                st.text_area("Email body", value=match.email_body, height=320)
            with sms_tab:
                st.text_input("SMS recipient", value=match.phone)
                st.text_area("SMS message", value=match.sms_message, height=180)

            operator = st.text_input("Prepared or sent by", value="Sabrina")
            notes = st.text_area(
                "Optional campaign, reply, or delivery notes",
                height=80,
            )
            email_column, sms_column = st.columns(2)
            if email_column.button(
                "Record Email Prepared/Sent",
                type="primary",
                use_container_width=True,
                disabled=not match.email_allowed,
            ):
                try:
                    updated = record_outreach(
                        ledger,
                        match,
                        channel=OutreachChannel.EMAIL,
                        sent_by=operator,
                        notes=notes,
                    )
                    intent_store.save(updated)
                    st.success("Email outreach recorded. The reactivation cooldown is now active.")
                    st.rerun()
                except BuyerIntentError as exc:
                    st.error(str(exc))
            if sms_column.button(
                "Record SMS Prepared/Sent",
                type="primary",
                use_container_width=True,
                disabled=not match.sms_allowed,
            ):
                try:
                    updated = record_outreach(
                        ledger,
                        match,
                        channel=OutreachChannel.SMS,
                        sent_by=operator,
                        notes=notes,
                    )
                    intent_store.save(updated)
                    st.success("SMS outreach recorded. The reactivation cooldown is now active.")
                    st.rerun()
                except BuyerIntentError as exc:
                    st.error(str(exc))

with signal_tab:
    if not buyers:
        st.info("Add buyer profiles before recording engagement.")
    else:
        buyer_options = {
            f"{buyer.first_name} {buyer.last_name}".strip(): buyer for buyer in buyers
        }
        property_options = {
            item.display_address or str(item.property_id): item for item in properties
        }
        with st.form("buyer_signal_form", clear_on_submit=True):
            buyer_name = st.selectbox("Buyer", list(buyer_options))
            property_name = st.selectbox(
                "Property — optional",
                ["No specific property", *property_options],
            )
            signal_type = st.selectbox(
                "Engagement signal",
                [
                    "dwelyx_click",
                    "property_view",
                    "email_open",
                    "sms_click",
                    "reply",
                    "call_connected",
                    "application_started",
                    "showing_requested",
                ],
            )
            signal_notes = st.text_area("Notes", height=80)
            save_signal = st.form_submit_button("Save Engagement Signal", type="primary")
        if save_signal:
            buyer = buyer_options[buyer_name]
            property_id = (
                property_options[property_name].property_id
                if property_name != "No specific property"
                else ""
            )
            updated = record_signal(
                ledger,
                buyer_id=buyer.buyer_id,
                signal_type=signal_type,
                property_id=property_id,
                notes=signal_notes,
            )
            intent_store.save(updated)
            st.success("Engagement signal saved. Buyer-intent scores will update immediately.")
            st.rerun()

with history_tab:
    if ledger.outreach:
        rows = [
            {
                "Sent": row.sent_at.astimezone().strftime("%Y-%m-%d %I:%M %p"),
                "Buyer ID": row.buyer_id,
                "Property ID": row.property_id,
                "Channel": row.channel.value,
                "Prepared/Sent By": row.sent_by or "—",
                "Outcome": row.outcome,
                "Notes": row.notes or "—",
            }
            for row in sorted(ledger.outreach, key=lambda item: item.sent_at, reverse=True)
        ]
        table = pd.DataFrame(rows)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Reactivation History (CSV)",
            data=table.to_csv(index=False).encode(),
            file_name="buyer_reactivation_history.csv",
            mime="text/csv",
        )
    else:
        st.info("No email or SMS reactivation outreach has been recorded yet.")

st.info(
    "The engine never contacts Do Not Contact buyers, never uses email or SMS without saved consent, "
    "and never promises approval. Final sending remains through your connected consent-based messaging system."
)
