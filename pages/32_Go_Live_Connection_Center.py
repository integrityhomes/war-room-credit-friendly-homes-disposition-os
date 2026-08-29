from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.go_live_connections import (
    automation_connection_sample_json,
    build_connection_status,
    connection_summary,
    dispatch_publishing_connection_test,
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
st.title("16-Channel Go-Live Connection Center")
st.caption(
    "Shows the outside handoffs and account setup that still stand between built software and controlled live operation."
)
st.info(
    "Secret values are never displayed. A present account ID or credential is not treated as launch authority, "
    "and an accepted handoff is not treated as proof that an external platform completed the action."
)

rows = build_connection_status(st.secrets)
summary = connection_summary(rows)
cols = st.columns(3)
cols[0].metric("Tracked setup categories", summary["total"])
cols[1].metric("Configured / present", summary["configured"])
cols[2].metric("Still missing", summary["remaining"])

frame = pd.DataFrame(
    [
        {
            "Connection / setup": row.name,
            "Status": row.status_label,
            "Required for": row.required_for,
            "Next step": row.next_step,
        }
        for row in rows
    ]
)
st.dataframe(frame, use_container_width=True, hide_index=True)

remaining = [row for row in rows if not row.configured]
if remaining:
    st.write("### Remaining external setup")
    for index, row in enumerate(remaining, start=1):
        st.write(f"{index}. **{row.name}** — {row.next_step}")
else:
    st.success(
        "All tracked setup categories have their required configuration present. "
        "That does not by itself authorize sending, publishing, ad launch, or spend."
    )

publishing = next(row for row in rows if row.key == "publishing_webhook")
st.write("### General Automation Webhook")
st.caption(
    "Blog and Market SEO are now CFH-owned routes and do not depend on this general webhook. "
    "Use it only for legacy/general external automation that still needs this handoff."
)
if publishing.configured:
    st.success("A general automation webhook URL is present in Streamlit Secrets.")
    tester = st.text_input("Connection test requested by", value="Shawn")
    st.caption(
        "This test sends no property, buyer, email, SMS, social post, ad, or spending instruction. "
        "It only confirms that CFH can reach the configured general automation webhook."
    )
    if st.button("Send safe general-webhook connection test", type="primary"):
        try:
            receipt = dispatch_publishing_connection_test(
                st.secrets,
                requested_by=tester,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"General webhook reached successfully — HTTP {receipt.status_code}.")
            if receipt.response_text:
                st.caption(f"Webhook response: {receipt.response_text}")
else:
    st.info(
        "The general automation webhook is not configured. That does not block CFH-owned Blog or Market SEO. "
        "Add AUTOMATION_WEBHOOK_URL only if a remaining legacy/general automation workflow needs it."
    )
    with st.expander("Show the safe test payload for a future general automation webhook"):
        st.code(automation_connection_sample_json(), language="json")

st.write("### Manual final steps that remain supported by design")
st.write(
    "Facebook Marketplace, Facebook Groups, Craigslist/local classifieds, and Nextdoor can remain human-confirmed. "
    "Instagram, TikTok, and YouTube can also use a manual final post when no approved social publication adapter is configured."
)

st.download_button(
    "Download go-live connection checklist CSV",
    data=frame.to_csv(index=False).encode("utf-8"),
    file_name="cfh_go_live_connection_checklist.csv",
    mime="text/csv",
)
