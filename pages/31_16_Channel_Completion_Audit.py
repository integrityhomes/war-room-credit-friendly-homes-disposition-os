from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_completion import build_channel_completion, completion_summary

st.set_page_config(page_title="16-Channel Completion Audit", page_icon="✅", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    with st.form("channel_audit_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


require_password()
st.title("16-Channel Completion Audit")
st.caption(
    "One honest view of what is built, tracked, usable now, and what still needs a connection, paid setup, or manual final post."
)

rows = build_channel_completion()
summary = completion_summary(rows)

metrics = st.columns(4)
metrics[0].metric("Registered channels", summary["total"])
metrics[1].metric("Built", summary["built"])
metrics[2].metric("Tracked", summary["tracked"])
metrics[3].metric("Ready to use", summary["ready_to_use"])

st.success(
    "A channel can be ready to use even when the final action is manual. "
    "This audit separates software completion from external platform connections."
)

data = pd.DataFrame(
    [
        {
            "Channel": row.name,
            "Built": "Yes" if row.built else "No",
            "Tracked": "Yes" if row.tracked else "No",
            "Ready to Use": "Yes" if row.ready_to_use else "No",
            "Operating Mode": row.operating_mode,
            "Next Requirement": row.next_requirement,
        }
        for row in rows
    ]
)
st.dataframe(data, use_container_width=True, hide_index=True)

st.write("### What still needs an outside connection or final platform action")
remaining = data[data["Next Requirement"] != "Ready now"]
st.dataframe(
    remaining[["Channel", "Operating Mode", "Next Requirement"]],
    use_container_width=True,
    hide_index=True,
)

st.download_button(
    "Download 16-channel completion audit CSV",
    data=data.to_csv(index=False).encode("utf-8"),
    file_name="cfh_16_channel_completion_audit.csv",
    mime="text/csv",
)

st.info(
    "Use this page before adding more channel code. If a channel is already Built + Tracked, "
    "the next work should be its real connection, account setup, or operating procedure instead of rebuilding it."
)
