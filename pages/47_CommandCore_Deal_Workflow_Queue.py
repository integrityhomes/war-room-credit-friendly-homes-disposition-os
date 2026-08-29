from __future__ import annotations

from typing import Any

import streamlit as st
from supabase import create_client

from cfh_disposition.auth import configured_password, password_matches

st.set_page_config(page_title="CommandCore Deal Workflow", page_icon="🔄", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Deal Workflow")
    with st.form("commandcore_deal_workflow_login"):
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


def call_crm(payload: dict[str, Any]) -> dict[str, Any]:
    response = get_supabase().functions.invoke("commandcore-crm-core", {"body": payload})
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    return data if isinstance(data, dict) else {}


def text(value: Any) -> str:
    return str(value or "").strip()


def list_records(entity: str) -> list[dict[str, Any]]:
    result = call_crm({"action": "list", "entity": entity, "limit": 500})
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def is_open(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() not in {
        "done",
        "completed",
        "closed",
        "cancelled",
        "canceled",
    }


require_password()
if st.sidebar.button("Log out", key="commandcore_deal_workflow_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Deal Workflow")
st.caption(
    "See analysis, offer, contract, title/closing, and marketing/disposition work that has been started from a deal."
)

try:
    tasks = [
        task
        for task in list_records("tasks")
        if is_open(task) and text(task.get("task_type")) == "deal_lifecycle_request"
    ]
    deals = list_records("deals")
except RuntimeError as exc:
    st.error(f"Deal workflow data could not be loaded: {exc}")
    st.stop()

deal_by_id = {text(deal.get("id")): deal for deal in deals}

missing = [task for task in tasks if text(task.get("prep_status")) == "missing_information"]
ready = [task for task in tasks if text(task.get("prep_status")) == "ready_for_specialist"]
unassigned = [task for task in tasks if not text(task.get("assigned_to"))]
contracts = [task for task in tasks if text(task.get("work_type")) == "prepare_contract"]
closing = [task for task in tasks if text(task.get("work_type")) == "title_closing"]

metrics = st.columns(6)
metrics[0].metric("Open lifecycle work", len(tasks))
metrics[1].metric("Ready", len(ready))
metrics[2].metric("Missing info", len(missing))
metrics[3].metric("Unassigned", len(unassigned))
metrics[4].metric("Contract prep", len(contracts))
metrics[5].metric("Title / closing", len(closing))

if missing:
    st.warning(f"{len(missing)} deal workflow request(s) are blocked by missing deal information.")
if unassigned:
    st.warning(f"{len(unassigned)} deal workflow request(s) do not currently have an owner.")
if not tasks:
    st.success("No open deal lifecycle requests are waiting.")
    st.stop()

status_filter = st.segmented_control(
    "Show",
    ["All", "Needs Information", "Ready", "Unassigned"],
    default="All",
)
work_filter = st.selectbox(
    "Work type",
    ["All", "deal_analysis", "prepare_offer", "prepare_contract", "title_closing", "marketing_dispo"],
)

filtered = tasks
if status_filter == "Needs Information":
    filtered = missing
elif status_filter == "Ready":
    filtered = ready
elif status_filter == "Unassigned":
    filtered = unassigned
if work_filter != "All":
    filtered = [task for task in filtered if text(task.get("work_type")) == work_filter]

for task in filtered:
    deal_id = text(links(task).get("deal_id") or task.get("deal_id"))
    deal = deal_by_id.get(deal_id, {})
    deal_name = text(deal.get("title")) or deal_id or "Unknown deal"
    prep_status = text(task.get("prep_status")) or "waiting_for_readiness_check"
    with st.container(border=True):
        top = st.columns([2, 1, 1])
        top[0].markdown(f"**{deal_name}**")
        top[1].write(text(task.get("title")) or text(task.get("work_type")) or "Lifecycle work")
        top[2].write(prep_status.replace("_", " ").title())
        st.caption(
            f"Owner: {text(task.get('assigned_to')) or 'Unassigned'}  •  "
            f"Priority: {text(task.get('priority')) or 'medium'}  •  "
            f"Coordination: {text(task.get('coordination_status')) or 'pending'}"
        )
        missing_info = task.get("missing_information")
        if isinstance(missing_info, list) and missing_info:
            st.write("Missing: " + ", ".join(text(item) for item in missing_info if text(item)))

st.divider()
st.caption(
    "This queue shows internal readiness and ownership only. It cannot approve or send offers, sign contracts, "
    "change legal terms, contact outside parties, or move money."
)
