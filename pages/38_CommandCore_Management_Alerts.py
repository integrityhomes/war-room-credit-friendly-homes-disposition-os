from __future__ import annotations

import json
from typing import Any
from urllib import request

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore Management Alerts", page_icon="⚠️", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Management Alerts")
    with st.form("commandcore_management_alerts_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


def call_commandcore(payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        return {}
    req = request.Request(
        f"{supabase_url}/functions/v1/commandcore-coverage-exception-ledger",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def text(value: Any) -> str:
    return str(value or "").strip()


def open_coverage_exceptions(*, key: str, primary: bool = False) -> None:
    if st.button(
        "Open Coverage Exceptions",
        key=key,
        type="primary" if primary else "secondary",
        use_container_width=True,
    ):
        st.switch_page("pages/37_CommandCore_Coverage_Exceptions.py")


require_password()

if st.sidebar.button("Log out", key="commandcore_management_alerts_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Management Alerts")
st.caption("See unresolved coverage problems that have aged past the normal response window and what management should handle next.")

result = call_commandcore({"action": "list", "days": 60, "status": "all"})
if not result.get("ok"):
    st.error("Management alerts could not be loaded. Nothing was changed.")
    st.stop()

raw = result.get("exceptions") if isinstance(result.get("exceptions"), list) else []
alerts = [
    item
    for item in raw
    if isinstance(item, dict)
    and text(item.get("status")).lower() != "resolved"
    and text(item.get("aging_level")).lower() in {"overdue", "escalated", "executive"}
]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Needs Management", len(alerts))
m2.metric("Executive", sum(text(item.get("aging_level")).lower() == "executive" for item in alerts))
m3.metric("Escalated", sum(text(item.get("aging_level")).lower() == "escalated" for item in alerts))
m4.metric("Overdue", sum(text(item.get("aging_level")).lower() == "overdue" for item in alerts))

if not alerts:
    with st.container(border=True):
        st.markdown("### Management alert queue is clear")
        st.write("No aged coverage exception currently needs management attention.")
        left, right = st.columns(2)
        if left.button("Open Operations", type="primary", use_container_width=True):
            st.switch_page("pages/39_CommandCore_Operations_Hub.py")
        if right.button("Review Owner Approvals", use_container_width=True):
            st.switch_page("pages/48_CommandCore_Owner_Approvals.py")
    st.stop()

rank = {"executive": 0, "escalated": 1, "overdue": 2}
alerts.sort(
    key=lambda item: (
        rank.get(text(item.get("aging_level")).lower(), 9),
        0 if text(item.get("severity")).lower() == "critical" else 1,
        text(item.get("created_at")),
    )
)

executive = [item for item in alerts if text(item.get("aging_level")).lower() == "executive"]
if executive:
    st.error(
        f"{len(executive)} coverage exception(s) require executive attention. "
        "Handle these before normal queue work."
    )

st.subheader("Management Priority Queue")
rows = []
for item in alerts:
    rows.append(
        {
            "Urgency": text(item.get("aging_level")).upper(),
            "Severity": text(item.get("severity")).upper(),
            "Owner": text(item.get("owner_name") or item.get("owner_id")) or "Unassigned",
            "Age Hours": item.get("age_hours"),
            "Problem": text(item.get("exception_type") or item.get("type")).replace("_", " ").title(),
            "Do This Next": text(item.get("recommended_action")) or "Review coverage and confirm safe ownership of urgent work.",
        }
    )

st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("Handle These First")
for index, item in enumerate(alerts[:10]):
    aging = text(item.get("aging_level")).upper()
    owner = text(item.get("owner_name") or item.get("owner_id") or "Unassigned")
    exception_type = text(item.get("exception_type") or item.get("type") or "coverage_exception").replace("_", " ").title()
    age_hours = item.get("age_hours")
    with st.container(border=True):
        st.markdown(f"#### {aging} — {exception_type}")
        summary = st.columns(3)
        summary[0].write(f"**Owner:** {owner}")
        summary[1].write(f"**Age:** {age_hours if age_hours is not None else 'Unknown'} hours")
        summary[2].write(f"**Severity:** {text(item.get('severity')).upper() or 'Not set'}")
        action = text(item.get("recommended_action")) or "Review coverage and confirm safe ownership of urgent work."
        st.write(f"**Do this next:** {action}")
        open_coverage_exceptions(key=f"open-coverage-exception-{index}", primary=index == 0)
        dispatch_id = text(item.get("dispatch_id"))
        if dispatch_id:
            with st.expander("Technical details", expanded=False):
                st.code(dispatch_id, language=None)

st.divider()
st.caption(
    "Read-only management visibility. This page cannot change task ownership, approvals, consent, readiness, "
    "budgets, legal terms, payments, communications, or external execution."
)
