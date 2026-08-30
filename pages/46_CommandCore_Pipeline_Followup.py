from __future__ import annotations

from datetime import date, datetime
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Pipeline", page_icon="📈", layout="wide")

PIPELINE_STAGES = [
    "New Lead",
    "Contacted",
    "Follow-Up",
    "Analyzing",
    "Offer Pending",
    "Offer Made",
    "Under Contract",
    "Title / Closing",
    "Marketing / Dispo",
    "Closed",
    "Dead / Not Moving Forward",
]
DEAL_STATUSES = ["Active", "On Hold", "Closed", "Dead"]


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Pipeline")
    with st.form("commandcore_pipeline_login"):
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


def upsert(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    return call_crm({"action": "upsert", "entity": entity, "record": record})


def choice_options(current: str, approved: list[str]) -> list[str]:
    if current and current not in approved:
        return [current, *approved]
    return list(approved)


def due_date(record: dict[str, Any]) -> date | None:
    raw = text(record.get("due_date") or record.get("due_at"))
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def is_open_task(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() not in {
        "done",
        "completed",
        "closed",
        "cancelled",
        "canceled",
    }


def deal_title(record: dict[str, Any]) -> str:
    return text(record.get("title")) or text(record.get("external_id")) or text(record.get("id"))


def open_deal_button(deal: dict[str, Any], *, key: str, label: str = "Open Deal") -> None:
    deal_id = text(deal.get("id"))
    if not deal_id:
        return
    if st.button(label, key=key, use_container_width=True):
        st.session_state["commandcore_selected_deal_id"] = deal_id
        st.switch_page("pages/45_CommandCore_Deal_Record.py")


def linked_deal_for_task(task: dict[str, Any], deals: list[dict[str, Any]]) -> dict[str, Any] | None:
    task_links = task.get("links") if isinstance(task.get("links"), dict) else {}
    deal_id = text(task_links.get("deal_id") if isinstance(task_links, dict) else "")
    return next((deal for deal in deals if text(deal.get("id")) == deal_id), None)


def show_followup_task(task: dict[str, Any], deals: list[dict[str, Any]], *, key_prefix: str) -> None:
    task_due = due_date(task)
    task_links = task.get("links") if isinstance(task.get("links"), dict) else {}
    deal_id = text(task_links.get("deal_id") if isinstance(task_links, dict) else "")
    linked_deal = linked_deal_for_task(task, deals)
    task_key = text(task.get("id")) or f"{deal_id}_{text(task.get('title'))}"
    with st.container(border=True):
        st.markdown(f"**{text(task.get('title')) or 'Follow up'}**")
        st.caption(
            f"Deal: {deal_title(linked_deal) if linked_deal else deal_id or 'Unlinked'}  |  "
            f"Due: {task_due.isoformat() if task_due else 'No date'}  |  "
            f"Owner: {text(task.get('assigned_to')) or 'Unassigned'}"
        )
        priority = text(task.get("priority"))
        if priority:
            st.caption(f"Priority: {priority.title()}")
        if linked_deal:
            open_deal_button(linked_deal, key=f"{key_prefix}_{task_key}")


require_password()
if st.sidebar.button("Log out", key="commandcore_pipeline_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Pipeline + Follow-Up")
st.caption(
    "See what needs attention now, what is coming next, and where every deal sits without searching twice."
)

deals = list_records("deals")
tasks = list_records("tasks")
open_tasks = [task for task in tasks if is_open_task(task)]
today = date.today()
overdue = [task for task in open_tasks if due_date(task) and due_date(task) < today]
due_today = [task for task in open_tasks if due_date(task) == today]
upcoming = sorted(
    [task for task in open_tasks if due_date(task) and due_date(task) > today],
    key=lambda task: due_date(task) or today,
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Open deals", len(deals))
m2.metric("Overdue", len(overdue))
m3.metric("Due today", len(due_today))
m4.metric("Upcoming", len(upcoming))

followup_tab, pipeline_tab = st.tabs(["Follow-Up Today", "Pipeline"])

with followup_tab:
    st.subheader("Needs attention now")
    attention = sorted(overdue + due_today, key=lambda task: due_date(task) or today)
    if not attention:
        st.success("No overdue or due-today follow-ups.")
    for task in attention:
        show_followup_task(task, deals, key_prefix="followup_attention")

    st.divider()
    st.subheader("Coming up next")
    if not upcoming:
        st.caption("No dated upcoming follow-ups are scheduled yet.")
    for task in upcoming[:20]:
        show_followup_task(task, deals, key_prefix="followup_upcoming")
    if len(upcoming) > 20:
        st.caption(f"Showing the next 20 of {len(upcoming)} upcoming follow-ups.")

    st.divider()
    st.subheader("Schedule next follow-up")
    if deals:
        chosen = st.selectbox("Deal for follow-up", deals, format_func=deal_title, key="followup_deal")
        open_deal_button(
            chosen,
            key=f"followup_selected_open_{text(chosen.get('id'))}",
            label="Open Selected Deal",
        )
        c1, c2 = st.columns(2)
        title = c1.text_input("Follow-up action", value="Follow up with seller")
        followup_date = c2.date_input("Due date", value=today)
        owner = st.text_input("Assigned to", value=text(chosen.get("assigned_to")))
        priority = st.selectbox("Priority", ["medium", "high", "low"], index=0)
        if st.button("Create follow-up", type="primary"):
            record = {
                "title": title,
                "status": "open",
                "priority": priority,
                "due_date": followup_date.isoformat(),
                "assigned_to": owner,
                "task_type": "crm_follow_up",
                "links": {"deal_id": text(chosen.get("id"))},
                "source": "commandcore-pipeline",
            }
            result = upsert("tasks", record)
            if result.get("ok"):
                st.success(
                    "Follow-up created. Due follow-ups are synced into the CommandCore Action Queue by the background service."
                )
                st.rerun()
            st.error(text(result.get("error")) or "Could not create the follow-up.")

with pipeline_tab:
    stages = sorted({text(deal.get("stage")) or "Unassigned Stage" for deal in deals})
    if not stages:
        st.info("No deals are in CommandCore yet.")
    else:
        columns = st.columns(min(len(stages), 5))
        for index, stage in enumerate(stages):
            with columns[index % len(columns)]:
                st.subheader(stage)
                stage_deals = [
                    deal
                    for deal in deals
                    if (text(deal.get("stage")) or "Unassigned Stage") == stage
                ]
                for deal in stage_deals:
                    deal_id = text(deal.get("id")) or str(index)
                    with st.container(border=True):
                        st.markdown(f"**{deal_title(deal)}**")
                        st.caption(f"Owner: {text(deal.get('assigned_to')) or 'Unassigned'}")
                        asking = text(deal.get("asking_price"))
                        offer = text(deal.get("offer_price"))
                        if asking or offer:
                            st.caption(f"Ask: {asking or '—'}  |  Offer: {offer or '—'}")
                        open_deal_button(deal, key=f"pipeline_open_{deal_id}")

    st.divider()
    st.subheader("Update deal stage")
    if deals:
        selected = st.selectbox("Deal", deals, format_func=deal_title)
        open_deal_button(
            selected,
            key=f"pipeline_selected_open_{text(selected.get('id'))}",
            label="Open Selected Deal",
        )
        current_stage = text(selected.get("stage")) or "New Lead"
        current_status = text(selected.get("status")) or "Active"
        stage_options = choice_options(current_stage, PIPELINE_STAGES)
        status_options = choice_options(current_status, DEAL_STATUSES)
        c1, c2 = st.columns(2)
        new_stage = c1.selectbox(
            "Stage",
            stage_options,
            index=stage_options.index(current_stage),
        )
        new_status = c2.selectbox(
            "Status",
            status_options,
            index=status_options.index(current_status),
        )
        st.caption("Use the standard choices so pipeline reporting stays consistent. Existing legacy values remain available until you change them.")
        if st.button("Save stage/status", type="primary"):
            result = upsert("deals", {**selected, "stage": new_stage, "status": new_status})
            if result.get("ok"):
                st.success("Deal pipeline updated.")
                st.rerun()
            st.error(text(result.get("error")) or "Could not update the deal.")

st.divider()
st.caption(
    "This workspace changes internal CRM records only. It does not send seller messages, make offers, sign contracts, "
    "move money, or perform external actions."
)
