from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.go_live_connections import (
    build_connection_status,
    connection_summary,
    dispatch_publishing_connection_test,
    make_connection_sample_json,
)

st.set_page_config(page_title="Go-Live Connection Center", page_icon="🔌", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    with st.form("go_live_connections_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


require_password()
st.title("15-Channel Go-Live Connection Center")
st.caption("Shows which outside connections still stand between the built channel system and live operation.")
st.info("Secret values are never displayed. This page only reports whether required connection settings are present.")

rows = build_connection_status(st.secrets)
summary = connection_summary(rows)
cols = st.columns(3)
cols[0].metric("Connections", summary["total"])
cols[1].metric("Connected", summary["connected"])
cols[2].metric("Remaining", summary["remaining"])

frame = pd.DataFrame(
    [
        {
            "Connection": row.name,
            "Status": "Connected" if row.configured else "Needs connection",
            "Required for": row.required_for,
            "Next step": row.next_step,
        }
        for row in rows
    ]
)
st.dataframe(frame, use_container_width=True, hide_index=True)

remaining = [row for row in rows if not row.configured]
if remaining:
    st.write("### Best next connection work")
    for index, row in enumerate(remaining, start=1):
        st.write(f"{index}. **{row.name}** — {row.next_step}")
else:
    st.success("All tracked external connection categories are configured. Proceed to controlled live testing.")

publishing = next(row for row in rows if row.key == "publishing_webhook")
st.write("### Make.com publishing connection")
if publishing.configured:
    st.success("A publishing webhook URL is present in Streamlit Secrets.")
    tester = st.text_input("Connection test requested by", value="Shawn")
    st.caption(
        "This test sends no property, buyer, email, SMS, ad, or spending instruction. "
        "It only confirms that the CFH app can reach the Make webhook."
    )
    if st.button("Send safe Make.com connection test", type="primary"):
        try:
            receipt = dispatch_publishing_connection_test(
                st.secrets,
                requested_by=tester,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"Make.com webhook reached successfully — HTTP {receipt.status_code}.")
            if receipt.response_text:
                st.caption(f"Webhook response: {receipt.response_text}")
else:
    st.warning(
        "Make.com is not connected yet. Create a Make Custom webhook, then save its URL as "
        "AUTOMATION_WEBHOOK_URL in Streamlit Secrets."
    )
    with st.expander("Show the safe test payload Make should receive"):
        st.code(make_connection_sample_json(), language="json")
    st.write(
        "After the URL is saved, return here and use the safe connection-test button before any live campaign is sent."
    )

st.write("### Channels that remain manual by design")
st.write(
    "Facebook Marketplace, Facebook Groups, Craigslist/local classifieds, and Nextdoor final publication "
    "remain human-confirmed where the platform requires or where manual posting is the safer operating choice."
)

st.download_button(
    "Download go-live connection checklist CSV",
    data=frame.to_csv(index=False).encode("utf-8"),
    file_name="cfh_go_live_connection_checklist.csv",
    mime="text/csv",
)
