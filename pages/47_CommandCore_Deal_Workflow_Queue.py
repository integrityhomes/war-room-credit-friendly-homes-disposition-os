from __future__ import annotations

from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Deal Work Queue", page_icon="🔄", layout="wide")

WORK_TYPE_LABELS = {
    "deal_analysis": "Deal Analysis",
    "prepare_offer": "Prepare Offer",
    "prepare_contract": "Prepare Contract",
    "title_closing": "Title / Closing",
    "marketing_dispo": "Marketing / Dispo",
}


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Deal Work Queue")
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


def work_type_label(value: Any) -> str:
    key = text(value)
    return WORK_TYPE_LABELS.get(key, key.replace("_", " ").title() or "Deal Work")


def prep_status_label(value: Any) -> str:
    status = text(value) or "waiting_for_readiness_check"
    labels = {
        "missing_information": "Needs Information",
        "ready_for_specialist": "Ready to Work",
        "waiting_for_readiness_check": "Checking Readiness",
    }
    return labels.get(status, status.replace("_", " ").title())


def open_deal(deal_id: str, *, key: str) -> None:
    if not deal_id:
        return
    if st.button("Open Deal", key=key, type="primary", use_container_width=True):
        st.session_state["commandcore_selected_deal_id"] = deal_id
        st.switch_page("pages/45_CommandCore_Deal_Record.py")


require_password()
if st.sidebar.button("Log out", key="commandcore_deal_workflow_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Deal Work Queue")
st.caption("See work across all deals: what is ready to move, what needs information, and what still needs an owner.")

try:
    tasks = [
        task
        for task in list_records("tasks")
        if is_open(task) and text(task.get("task_type")) == "deal_lifecycle_request"
    ]
    deals = list_records("deals")
except RuntimeError as exc:
    st.error(f"Deal work data could not be loaded: {exc}")
    st.stop()

deal_by_id = {text(deal.get("id")): deal for deal in deals}

missing = [task for task in tasks if text(task.get("prep_status")) == "missing_information"]
ready = [task for task in tasks if text(task.get("prep_status")) == "ready_for_specialist"]
unassigned = [task for task in tasks if not text(task.get("assigned_to"))]
contracts = [task for task in tasks if text(task.get("work_type")) == "prepare_contract"]
closing = [task for task in tasks if text(task.get("work_type")) == "title_closing"]

metrics = st.columns(6)
metrics[0].metric("Open Work", len(tasks))
metrics[1].metric("Ready to Work", len(ready))
metrics[2].metric("Needs Information", len(missing))
metrics[3].metric("Needs Owner", len(unassigned))
metrics[4].metric("Contract Prep", len(contracts))
metrics[5].metric("Title / Closing", len(closing))

if missing:
    st.warning(f"{len(missing)} deal work item(s) are waiting for missing deal information.")
if unassigned:
    st.warning(f"{len(unassigned)} deal work item(s) do not currently have an owner.")
if not tasks:
    with st.container(border=True):
        st.markdown("### No deal work is waiting")
        st.write("There is no open lifecycle work in the queue right now.")
        left, right = st.columns(2)
        if left.button("Open Deal Workspace", type="primary", use_container_width=True):
            st.switch_page("pages/45_CommandCore_Deal_Record.py")
        if right.button("Add New Lead", use_container_width=True):
            st.switch_page("pages/44_CommandCore_CRM.py")
        st.caption("New deal work will appear here automatically when it is started from a deal.")
    st.stop()

status_filter = st.segmented_control(
    "Show",
    ["All", "Needs Information", "Ready", "Unassigned"],
    default="All",
)
work_filter = st.selectbox(
    "Work type",
    ["All", *WORK_TYPE_LABELS],
    format_func=lambda value: "All" if value == "All" else work_type_label(value),
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
    with st.container(border=True):
        st.markdown(f"#### {deal_name}")
        top = st.columns([2, 1])
        top[0].write(f"**Next step:** {text(task.get('title')) or work_type_label(task.get('work_type'))}")
        top[1].write(f"**Status:** {prep_status_label(task.get('prep_status'))}")
        owner = text(task.get("assigned_to")) or "Unassigned"
        priority = (text(task.get("priority")) or "medium").title()
        st.caption(f"Owner: {owner}  •  Priority: {priority}")

        missing_info = task.get("missing_information")
        if isinstance(missing_info, list) and missing_info:
            st.warning("Missing information: " + ", ".join(text(item) for item in missing_info if text(item)))

        if deal_id:
            open_deal(deal_id, key=f"deal-next-step-{text(task.get('id')) or deal_id}")

        coordination_status = text(task.get("coordination_status")) or "pending"
        with st.expander("More details", expanded=False):
            st.write(f"**Work type:** {work_type_label(task.get('work_type'))}")
            st.write(f"**Coordination:** {coordination_status.replace('_', ' ').title()}")
            if text(task.get("id")):
                st.caption(f"Task ID: {text(task.get('id'))}")

st.divider()
st.caption(
    "This queue shows internal readiness and ownership only. It cannot approve or send offers, sign contracts, "
    "change legal terms, contact outside parties, or move money."
)
