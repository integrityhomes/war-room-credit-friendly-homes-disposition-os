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


require_password()

if st.sidebar.button("Log out", key="commandcore_management_alerts_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Management Alerts")
st.caption("One place for unresolved coverage failures that have aged past their normal response window.")

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
    st.success("No aged coverage exceptions currently need management attention.")
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
        f"{len(executive)} coverage exception(s) have aged into EXECUTIVE ATTENTION. "
        "These should be reviewed before normal queue work."
    )

st.subheader("Management Priority Queue")
rows = []
for item in alerts:
    rows.append(
        {
            "Aging": text(item.get("aging_level")).upper(),
            "Severity": text(item.get("severity")).upper(),
            "Owner": text(item.get("owner_name") or item.get("owner_id")),
            "Status": text(item.get("status") or "open").upper(),
            "Age Hours": item.get("age_hours"),
            "Type": text(item.get("exception_type") or item.get("type")).replace("_", " ").title(),
            "Dispatch": text(item.get("dispatch_id")),
            "Recommended Action": text(item.get("recommended_action")),
        }
    )

st.dataframe(rows, use_container_width=True, hide_index=True)

st.subheader("What To Handle First")
for item in alerts[:10]:
    aging = text(item.get("aging_level")).upper()
    owner = text(item.get("owner_name") or item.get("owner_id") or "Unknown owner")
    exception_type = text(item.get("exception_type") or item.get("type") or "coverage_exception").replace("_", " ").title()
    age_hours = item.get("age_hours")
    with st.expander(f"{aging} — {owner} — {exception_type}", expanded=aging == "EXECUTIVE"):
        st.write(f"**Age:** {age_hours if age_hours is not None else 'Unknown'} hours")
        dispatch_id = text(item.get("dispatch_id"))
        if dispatch_id:
            st.write(f"**Dispatch:** {dispatch_id}")
        action = text(item.get("recommended_action")) or "Review coverage and confirm safe ownership of urgent work."
        st.write(f"**Do this next:** {action}")
        st.caption("Open CommandCore Coverage Exceptions to acknowledge, resolve, or reopen this exception.")

st.divider()
st.caption(
    "Read-only management visibility. This page cannot change task ownership, approvals, consent, readiness, "
    "budgets, legal terms, payments, communications, or external execution."
)
