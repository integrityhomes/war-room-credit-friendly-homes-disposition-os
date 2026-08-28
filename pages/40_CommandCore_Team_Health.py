from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from urllib import request

import streamlit as st
from supabase import create_client

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore Team Health", page_icon="📊", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Team Health")
    with st.form("commandcore_team_health_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_supabase():
    url = str(st.secrets.get("SUPABASE_URL", "")).strip()
    key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
    return create_client(url, key)


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


def load_queue_items() -> list[dict[str, Any]]:
    client = get_supabase()
    rows = client.storage.from_(ACTION_BUCKET).list("dispatches") or []
    items: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(ACTION_BUCKET).download(f"dispatches/{name}")
            snapshot = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(snapshot, dict):
            continue
        for item in snapshot.get("items") if isinstance(snapshot.get("items"), list) else []:
            if isinstance(item, dict):
                items.append(item)
    return items


def text(value: Any) -> str:
    return str(value or "").strip()


def is_open(item: dict[str, Any]) -> bool:
    return text(item.get("readiness")).upper() in {"HOLD", "MANUAL", "BLOCKED"}


def health_level(load_ratio: float, critical: int, blocked: int, availability: str, active: bool) -> str:
    if not active:
        return "INACTIVE"
    if critical or load_ratio >= 1.0 or (availability == "unavailable" and load_ratio > 0):
        return "CRITICAL"
    if load_ratio >= 0.8 or blocked or availability == "away":
        return "WATCH"
    return "HEALTHY"


require_password()

if st.sidebar.button("Log out", key="commandcore_team_health_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Team Workload Health")
st.caption(
    "Shows workload, capacity, coverage risk, and unresolved coverage failures so management can see where the team is strained."
)

try:
    queue_items = load_queue_items()
except Exception as exc:
    st.error(f"CommandCore work could not be loaded: {exc}")
    st.stop()

team_result = call_commandcore("commandcore-team-registry", {"action": "list"})
exception_result = call_commandcore(
    "commandcore-coverage-exception-ledger",
    {"action": "list", "days": 60, "status": "all"},
)

members = team_result.get("members") if isinstance(team_result.get("members"), list) else []
members = [item for item in members if isinstance(item, dict)]
exceptions = exception_result.get("exceptions") if isinstance(exception_result.get("exceptions"), list) else []
exceptions = [
    item
    for item in exceptions
    if isinstance(item, dict) and text(item.get("status")).lower() != "resolved"
]

assigned: dict[str, list[dict[str, Any]]] = defaultdict(list)
for item in queue_items:
    if not is_open(item):
        continue
    owner_id = text(item.get("owner_id"))
    if owner_id:
        assigned[owner_id].append(item)

exceptions_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
for item in exceptions:
    owner_id = text(item.get("owner_id"))
    if owner_id:
        exceptions_by_owner[owner_id].append(item)

rows: list[dict[str, Any]] = []
for member in members:
    owner_id = text(member.get("id"))
    work = assigned.get(owner_id, [])
    max_load = int(member.get("max_load", 20) or 20)
    open_work = len(work)
    ratio = open_work / max_load if max_load > 0 else 1.0
    critical_exceptions = sum(
        text(item.get("severity")).lower() == "critical" for item in exceptions_by_owner.get(owner_id, [])
    )
    blocked = sum(text(item.get("readiness")).upper() == "BLOCKED" for item in work)
    manual = sum(text(item.get("readiness")).upper() == "MANUAL" for item in work)
    high = sum(text(item.get("priority")).lower() == "high" for item in work)
    availability = text(member.get("availability") or "available").lower()
    active = member.get("active") is not False
    backups = member.get("backup_owner_ids") if isinstance(member.get("backup_owner_ids"), list) else []
    level = health_level(ratio, critical_exceptions, blocked, availability, active)
    risk_notes: list[str] = []
    if ratio >= 1.0:
        risk_notes.append("at or over capacity")
    elif ratio >= 0.8:
        risk_notes.append("near capacity")
    if availability == "unavailable" and open_work:
        risk_notes.append("unavailable with open work")
    if open_work and not backups:
        risk_notes.append("no backup configured")
    if critical_exceptions:
        risk_notes.append(f"{critical_exceptions} critical coverage exception(s)")
    if blocked:
        risk_notes.append(f"{blocked} blocked item(s)")

    rows.append(
        {
            "Health": level,
            "Team Member": text(member.get("name") or owner_id),
            "Availability": availability.title(),
            "Open Work": open_work,
            "Capacity": max_load,
            "Load %": round(ratio * 100),
            "High": high,
            "Blocked": blocked,
            "Manual": manual,
            "Coverage Exceptions": len(exceptions_by_owner.get(owner_id, [])),
            "Backups": len(backups),
            "Risk": ", ".join(risk_notes) or "No immediate risk detected",
        }
    )

rank = {"CRITICAL": 0, "WATCH": 1, "HEALTHY": 2, "INACTIVE": 3}
rows.sort(key=lambda row: (rank.get(str(row["Health"]), 9), -int(row["Load %"])))

critical_team = sum(row["Health"] == "CRITICAL" for row in rows)
watch_team = sum(row["Health"] == "WATCH" for row in rows)
near_capacity = sum(int(row["Load %"]) >= 80 for row in rows if row["Health"] != "INACTIVE")
unassigned = sum(1 for item in queue_items if is_open(item) and not text(item.get("owner_id")))
executive_exceptions = sum(text(item.get("aging_level")).lower() == "executive" for item in exceptions)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Critical Team Risk", critical_team)
c2.metric("Watch", watch_team)
c3.metric("Near / Over Capacity", near_capacity)
c4.metric("Unassigned Work", unassigned)
c5.metric("Executive Coverage Risk", executive_exceptions)

st.subheader("Business Needs Attention Now")
attention: list[str] = []
if executive_exceptions:
    attention.append(f"{executive_exceptions} coverage exception(s) have reached executive attention.")
if critical_team:
    attention.append(f"{critical_team} team member(s) are in a critical workload or coverage state.")
if unassigned:
    attention.append(f"{unassigned} open work item(s) have no owner assigned.")
if near_capacity:
    attention.append(f"{near_capacity} active team member(s) are at 80% capacity or higher.")

if attention:
    for message in attention:
        st.error(message)
else:
    st.success("No team-level workload or coverage condition currently needs executive attention.")

st.subheader("Team Health")
if rows:
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No team members are currently registered in CommandCore.")

st.subheader("Highest-Risk Team Members")
for row in rows[:10]:
    if row["Health"] not in {"CRITICAL", "WATCH"}:
        continue
    with st.expander(
        f"{row['Health']} — {row['Team Member']} — {row['Load %']}% load",
        expanded=row["Health"] == "CRITICAL",
    ):
        st.write(f"**Availability:** {row['Availability']}")
        st.write(f"**Open work:** {row['Open Work']} of {row['Capacity']} capacity")
        st.write(f"**High / Blocked / Manual:** {row['High']} / {row['Blocked']} / {row['Manual']}")
        st.write(f"**Coverage exceptions:** {row['Coverage Exceptions']}")
        st.write(f"**Backup owners configured:** {row['Backups']}")
        st.write(f"**Why this needs attention:** {row['Risk']}")

st.divider()
st.caption(
    "Read-only management visibility. This page cannot change assignments, approvals, consent, readiness, budgets, "
    "legal terms, payments, communications, or external execution."
)
