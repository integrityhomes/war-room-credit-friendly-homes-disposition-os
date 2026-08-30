from __future__ import annotations

import pandas as pd
import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.channel_completion import build_channel_completion, completion_summary

st.set_page_config(page_title="CommandCore Marketing Setup Status", page_icon="✅", layout="wide")


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
st.title("CommandCore Marketing Setup Status")
st.caption("See what marketing can operate now, what still needs a connection, and what to finish next.")

rows = build_channel_completion()
summary = completion_summary(rows)

metrics = st.columns(5)
metrics[0].metric("Marketing Channels", summary["total"])
metrics[1].metric("Ready Now", summary["ready_to_use"])
metrics[2].metric("Not Ready Yet", summary["not_ready_now"])
metrics[3].metric("Connection Needed", summary["connection_required"])
metrics[4].metric("Manual Final Step", summary["manual_final_step_required"])

if summary["not_ready_now"]:
    st.warning(
        f"{summary['not_ready_now']} marketing channel(s) still need an operating step before they should be treated as live."
    )
    left, right = st.columns(2)
    if left.button("Open Connections", type="primary", use_container_width=True):
        st.switch_page("pages/32_Go_Live_Connection_Center.py")
    if right.button("Open Marketing Home", use_container_width=True):
        st.switch_page("pages/90_CFH_Marketing_Dispo.py")
else:
    st.success("Every registered marketing channel is operational in its intended mode.")
    if st.button("Open Marketing Home", type="primary"):
        st.switch_page("pages/90_CFH_Marketing_Dispo.py")

st.write("### What still needs to be finished")
data = pd.DataFrame(
    [
        {
            "Channel": row.name,
            "Ready Now": "Yes" if row.ready_to_use else "No",
            "Operating Mode": row.operating_mode,
            "Next Requirement": row.next_requirement,
            "Connection Required": "Yes" if row.connection_required else "No",
            "Manual Final Step": "Yes" if row.manual_final_step_required else "No",
            "Software Built": "Yes" if row.built else "No",
            "Tracked": "Yes" if row.tracked else "No",
            "Completion State": row.completion_state,
        }
        for row in rows
    ]
)
remaining = data[data["Ready Now"] == "No"]
if remaining.empty:
    st.success("No channel setup or connection work remains.")
else:
    st.dataframe(
        remaining[["Channel", "Operating Mode", "Next Requirement"]],
        use_container_width=True,
        hide_index=True,
    )

with st.expander("Complete marketing setup detail", expanded=False):
    st.caption(
        "Assisted/manual channels can be operational even when a human must make the final platform post. "
        "Connection-required channels remain Not Ready until the real sender, publisher, ad account, or approved publication path is verified."
    )
    st.dataframe(data, use_container_width=True, hide_index=True)

    st.write("### Complete assisted/manual workflows")
    manual = data[(data["Ready Now"] == "Yes") & (data["Manual Final Step"] == "Yes")]
    if manual.empty:
        st.caption("No manual-final-step channels are currently classified as complete.")
    else:
        st.dataframe(
            manual[["Channel", "Operating Mode", "Next Requirement"]],
            use_container_width=True,
            hide_index=True,
        )

    st.download_button(
        "Download Marketing Setup Audit CSV",
        data=data.to_csv(index=False).encode("utf-8"),
        file_name="commandcore_marketing_setup_audit.csv",
        mime="text/csv",
    )

st.caption(
    "This is a read-only setup-status view. It does not publish campaigns, connect accounts, change property facts, or perform external actions."
)
