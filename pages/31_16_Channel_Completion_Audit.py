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
    "One honest view of what software exists, what is tracked, what can operate now, "
    "and what still needs a connection or final platform step."
)

rows = build_channel_completion()
summary = completion_summary(rows)

metrics = st.columns(6)
metrics[0].metric("Registered channels", summary["total"])
metrics[1].metric("Software built", summary["built"])
metrics[2].metric("Tracked", summary["tracked"])
metrics[3].metric("Ready now", summary["ready_to_use"])
metrics[4].metric("Connection needed", summary["connection_required"])
metrics[5].metric("Manual final step", summary["manual_final_step_required"])

if summary["not_ready_now"]:
    st.warning(
        f"Software exists for all {summary['built']} registered channels, but "
        f"{summary['not_ready_now']} are not fully operational yet. "
        "A page or campaign package is not counted as live merely because the code exists."
    )
else:
    st.success("Every registered channel is operational in its intended mode.")

st.info(
    "Assisted/manual channels can be complete even when a human must make the final platform post. "
    "Connection-required channels stay Not Ready until the real sender, publisher, ad account, or "
    "approved publication path is connected and verified."
)

data = pd.DataFrame(
    [
        {
            "Channel": row.name,
            "Software Built": "Yes" if row.built else "No",
            "Tracked": "Yes" if row.tracked else "No",
            "Ready Now": "Yes" if row.ready_to_use else "No",
            "Completion State": row.completion_state,
            "Operating Mode": row.operating_mode,
            "Connection Required": "Yes" if row.connection_required else "No",
            "Manual Final Step": "Yes" if row.manual_final_step_required else "No",
            "Next Requirement": row.next_requirement,
        }
        for row in rows
    ]
)
st.dataframe(data, use_container_width=True, hide_index=True)

st.write("### Not fully operational yet")
remaining = data[data["Ready Now"] == "No"]
if remaining.empty:
    st.success("No channel software or connection work remains.")
else:
    st.dataframe(
        remaining[
            [
                "Channel",
                "Completion State",
                "Operating Mode",
                "Next Requirement",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

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
    "Download 16-channel completion audit CSV",
    data=data.to_csv(index=False).encode("utf-8"),
    file_name="cfh_16_channel_completion_audit.csv",
    mime="text/csv",
)

st.info(
    "Use this page as the marketing/disposition completion checklist. Finish the Not Ready items "
    "before calling the tied-in marketing apps fully operational. Do not rebuild channels whose "
    "software is already complete; connect or finish their missing operating path instead."
)
