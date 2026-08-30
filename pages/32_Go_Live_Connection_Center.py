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

st.set_page_config(page_title="CommandCore Connections", page_icon="🔌", layout="wide")


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
st.title("CommandCore Connections")
st.caption("See which outside accounts or handoffs still need setup before their related marketing paths can operate.")
st.info(
    "Secret values are never displayed. A configured account or credential is not launch authority, and a successful handoff is not proof that an outside platform completed an action."
)

rows = build_connection_status(st.secrets)
summary = connection_summary(rows)
cols = st.columns(3)
cols[0].metric("Setup Categories", summary["total"])
cols[1].metric("Configured", summary["configured"])
cols[2].metric("Still Missing", summary["remaining"])

remaining = [row for row in rows if not row.configured]
if remaining:
    st.warning(f"{len(remaining)} connection or setup item(s) still need attention.")
    st.write("### Finish These Next")
    for row in remaining:
        with st.container(border=True):
            st.markdown(f"**{row.name}**")
            st.write(row.next_step)
            st.caption(f"Needed for: {row.required_for}")
else:
    st.success(
        "All tracked setup categories have their required configuration present. "
        "This does not by itself authorize sending, publishing, ad launch, or spend."
    )

left, right = st.columns(2)
if left.button("Open Marketing Setup Status", type="primary", use_container_width=True):
    st.switch_page("pages/31_16_Channel_Completion_Audit.py")
if right.button("Open Marketing Home", use_container_width=True):
    st.switch_page("pages/90_CFH_Marketing_Dispo.py")

frame = pd.DataFrame(
    [
        {
            "Connection / Setup": row.name,
            "Status": row.status_label,
            "Required For": row.required_for,
            "Next Step": row.next_step,
        }
        for row in rows
    ]
)

with st.expander("All connection and setup details", expanded=False):
    st.dataframe(frame, use_container_width=True, hide_index=True)

    st.write("### Manual final steps supported by design")
    st.write(
        "Facebook Marketplace, Facebook Groups, Craigslist/local classifieds, and Nextdoor can remain human-confirmed. "
        "Instagram, TikTok, and YouTube can also use a manual final post when no approved social publication adapter is configured."
    )

    st.download_button(
        "Download Connection Checklist CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="commandcore_connection_checklist.csv",
        mime="text/csv",
    )

publishing = next(row for row in rows if row.key == "publishing_webhook")
with st.expander("Advanced: general automation webhook", expanded=False):
    st.caption(
        "Blog and Market SEO are CommandCore-owned routes and do not depend on this general webhook. "
        "Use this only for legacy/general external automation that still needs the handoff."
    )
    if publishing.configured:
        st.success("A general automation webhook URL is present in Streamlit Secrets.")
        tester = st.text_input("Connection test requested by", value="CommandCore Owner")
        st.caption(
            "This test sends no property, buyer, email, SMS, social post, ad, or spending instruction. "
            "It only confirms that CommandCore can reach the configured general automation webhook."
        )
        if st.button("Send Safe General-Webhook Test", type="primary"):
            try:
                receipt = dispatch_publishing_connection_test(st.secrets, requested_by=tester)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success(f"General webhook reached successfully — HTTP {receipt.status_code}.")
                if receipt.response_text:
                    st.caption(f"Webhook response: {receipt.response_text}")
    else:
        st.info(
            "The general automation webhook is not configured. That does not block CommandCore-owned Blog or Market SEO. "
            "Add AUTOMATION_WEBHOOK_URL only if a remaining legacy/general automation workflow needs it."
        )
        with st.expander("Show safe future test payload"):
            st.code(automation_connection_sample_json(), language="json")
