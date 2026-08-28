from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib import request

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore Coverage", page_icon="🛡️", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Coverage")
    with st.form("commandcore_coverage_login"):
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
        with request.urlopen(req, timeout=20) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


@st.cache_data(ttl=30)
def load_team() -> list[dict[str, Any]]:
    result = call_commandcore("commandcore-team-registry", {"action": "list"})
    members = result.get("members") if isinstance(result, dict) else []
    return [item for item in members if isinstance(item, dict)] if isinstance(members, list) else []


def member_label(member: dict[str, Any]) -> str:
    name = str(member.get("name", "") or member.get("id", "")).strip()
    member_id = str(member.get("id", "") or "").strip()
    return f"{name} ({member_id})" if member_id and member_id != name else name


def iso_from_inputs(day_value: Any, time_value: Any) -> str:
    combined = datetime.combine(day_value, time_value)
    return combined.replace(tzinfo=timezone.utc).isoformat()


def show_detection(detection: dict[str, Any]) -> None:
    level = str(detection.get("escalation_level", "normal") or "normal").upper()
    status = str(detection.get("handoff_status", "unknown") or "unknown").replace("_", " ").title()
    elapsed = detection.get("elapsed_minutes")
    if level == "CRITICAL":
        st.error(f"CRITICAL COVERAGE GAP — {status}")
    elif level == "OVERDUE":
        st.warning(f"OVERDUE HANDOFF — {status}")
    elif level == "PENDING":
        st.info(f"Awaiting takeover acknowledgment — {elapsed} minutes since shift start")
    else:
        st.success(f"Handoff status: {status}")
    if elapsed is not None:
        st.caption(f"Elapsed since shift start: {elapsed} minutes")
    recommendation = str(detection.get("recommended_action", "") or "").strip()
    if recommendation:
        st.write(f"**CommandCore recommendation:** {recommendation}")


require_password()

if st.sidebar.button("Log out", key="commandcore_coverage_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Coverage")
st.caption(
    "Checks whether an incoming shift was acknowledged and safely routes uncovered internal work to a designated backup when needed."
)

team = load_team()
active_team = [member for member in team if member.get("active") is not False]
if not active_team:
    st.info("No active team members are available in the Team Registry yet.")
    st.stop()

selected_label = st.selectbox("Incoming team member", [member_label(member) for member in active_team])
selected = next(member for member in active_team if member_label(member) == selected_label)
owner_id = str(selected.get("id", "") or "").strip()

c1, c2 = st.columns(2)
with c1:
    shift_date = st.date_input("Shift start date")
with c2:
    default_time = datetime.now().replace(second=0, microsecond=0).time()
    shift_time = st.time_input("Shift start time", value=default_time)

grace_minutes = st.number_input("Takeover grace period (minutes)", min_value=0, max_value=120, value=15, step=5)
shift_started_at = iso_from_inputs(shift_date, shift_time)

detection = call_commandcore(
    "commandcore-missed-handoff",
    {
        "owner_id": owner_id,
        "shift_started_at": shift_started_at,
        "grace_minutes": int(grace_minutes),
    },
)

if not detection.get("ok"):
    st.error("Coverage status could not be checked. Nothing was changed.")
    st.stop()

show_detection(detection)

handoff_status = str(detection.get("handoff_status", "") or "").lower()
requires_attention = detection.get("requires_attention") is True

if not requires_attention:
    st.caption("No backup routing is needed right now.")
else:
    recommendation = call_commandcore(
        "commandcore-coverage-escalation",
        {
            "owner_id": owner_id,
            "handoff_status": handoff_status,
            "apply": False,
        },
    )
    if recommendation.get("backup_available") is True:
        backup_name = str(recommendation.get("backup_owner_name", "") or "Designated backup")
        backup_id = str(recommendation.get("backup_owner_id", "") or "")
        st.warning(f"Designated backup available: {backup_name}")
        if backup_id:
            st.caption(f"Backup owner ID: {backup_id}")

        dispatch_id = st.text_input(
            "Dispatch ID to cover",
            placeholder="Paste the dispatch ID for the uncovered internal work",
        ).strip()
        st.caption(
            "Applying coverage changes internal assignment only. It cannot approve a deal, change consent, alter readiness, authorize spending, or send anything externally."
        )
        if st.button("Route uncovered work to backup", type="primary"):
            if not dispatch_id:
                st.error("A dispatch ID is required before CommandCore can change internal assignment.")
            else:
                result = call_commandcore(
                    "commandcore-coverage-escalation",
                    {
                        "owner_id": owner_id,
                        "dispatch_id": dispatch_id,
                        "handoff_status": handoff_status,
                        "apply": True,
                    },
                )
                if result.get("ok") and result.get("applied"):
                    st.success("Coverage reassignment was requested through the safe workload rebalancer.")
                else:
                    st.error("Coverage could not be applied. No external action was taken.")
    elif recommendation.get("escalation_required"):
        st.error("No eligible designated backup is available. Manager review is required.")
        message = str(recommendation.get("recommended_action", "") or "").strip()
        if message:
            st.write(message)

st.divider()
st.caption(
    "Coverage controls affect internal task assignment only. They never change readiness, approvals, consent, budgets, legal terms, payments, or external execution permissions."
)
