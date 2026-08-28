from __future__ import annotations

import json
from typing import Any
from urllib import request

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore Coverage Exceptions", page_icon="🚨", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Coverage Exceptions")
    with st.form("commandcore_coverage_exceptions_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


def call_commandcore(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        return {}
    req = request.Request(
        f"{supabase_url}/functions/v1/{function_name}",
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


def management_action(item: dict[str, Any]) -> str:
    recommended = text(item.get("recommended_action"))
    if recommended:
        return recommended
    exception_type = text(item.get("type") or item.get("exception_type")).lower()
    if "no_backup" in exception_type or "backup" in exception_type:
        return "Assign or activate a qualified backup owner, then verify the uncovered work was routed."
    if "reassignment" in exception_type or "dispatch" in exception_type:
        return "Review the affected dispatch and manually confirm a safe internal owner assignment."
    return "Review the coverage event, confirm ownership of urgent work, and document the resolution."


require_password()

if st.sidebar.button("Log out", key="commandcore_coverage_exceptions_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Coverage Exceptions")
st.caption(
    "Shows unresolved missed-shift coverage failures so operational problems cannot disappear in backend logs."
)

c1, c2 = st.columns([1, 2])
with c1:
    days = st.selectbox("Look back", [7, 14, 30, 60], index=1, format_func=lambda value: f"Last {value} days")
with c2:
    st.caption("Open exceptions only. This page is read-only and cannot change assignments or execute externally.")

result = call_commandcore(
    "commandcore-coverage-exception-ledger",
    {"action": "list", "days": int(days), "status": "open"},
)
if not result.get("ok"):
    st.error("Coverage exceptions could not be loaded. Nothing was changed.")
    st.stop()

exceptions = result.get("exceptions") if isinstance(result.get("exceptions"), list) else []
exceptions = [item for item in exceptions if isinstance(item, dict)]

m1, m2, m3 = st.columns(3)
m1.metric("Open Exceptions", len(exceptions))
m2.metric("Critical", sum(text(item.get("severity")).lower() == "critical" for item in exceptions))
m3.metric("Warnings", sum(text(item.get("severity")).lower() == "warning" for item in exceptions))

if not exceptions:
    st.success("No unresolved coverage exceptions were found in this period.")
    st.stop()

owners = sorted({text(item.get("owner_name") or item.get("owner_id")) for item in exceptions if text(item.get("owner_name") or item.get("owner_id"))})
severities = sorted({text(item.get("severity")).lower() for item in exceptions if text(item.get("severity"))})

f1, f2 = st.columns(2)
with f1:
    owner_filter = st.selectbox("Affected owner", ["All"] + owners)
with f2:
    severity_filter = st.selectbox("Severity", ["All"] + [value.title() for value in severities])

filtered = []
for item in exceptions:
    owner = text(item.get("owner_name") or item.get("owner_id"))
    severity = text(item.get("severity")).lower()
    if owner_filter != "All" and owner != owner_filter:
        continue
    if severity_filter != "All" and severity != severity_filter.lower():
        continue
    filtered.append(item)

priority = {"critical": 0, "warning": 1, "info": 2}
filtered.sort(key=lambda item: (priority.get(text(item.get("severity")).lower(), 9), text(item.get("created_at"))), reverse=False)

st.subheader("Needs Management Attention")
for item in filtered:
    severity = text(item.get("severity") or "warning").upper()
    owner = text(item.get("owner_name") or item.get("owner_id") or "Unknown owner")
    exception_type = text(item.get("type") or item.get("exception_type") or "coverage_exception").replace("_", " ").title()
    created_at = text(item.get("created_at"))
    dispatch_id = text(item.get("dispatch_id"))
    shift_started_at = text(item.get("shift_started_at"))
    title = f"{severity} — {owner} — {exception_type}"
    with st.expander(title, expanded=severity == "CRITICAL"):
        if severity == "CRITICAL":
            st.error("Immediate management review recommended.")
        else:
            st.warning("Management review needed.")
        d1, d2 = st.columns(2)
        d1.write(f"**Created:** {created_at or 'Not recorded'}")
        d2.write(f"**Shift started:** {shift_started_at or 'Not recorded'}")
        if dispatch_id:
            st.write(f"**Dispatch:** {dispatch_id}")
        reason = text(item.get("reason") or item.get("message") or item.get("context"))
        if reason:
            st.write(f"**What failed:** {reason}")
        st.write(f"**What management should do:** {management_action(item)}")
        exception_id = text(item.get("exception_id"))
        if exception_id:
            st.caption(f"Exception ID: {exception_id}")

st.divider()
st.caption(
    "Read-only operational visibility. This screen cannot approve deals, change readiness, modify consent, authorize spending, move money, send communications, or execute externally."
)
