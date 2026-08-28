from __future__ import annotations

from datetime import date, datetime
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Pipeline", page_icon="📈", layout="wide")


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
    return text(record.get("status")).lower() not in {"done", "completed", "closed", "cancelled", "canceled"}


def deal_title(record: dict[str, Any]) -> str:
    return text(record.get("title")) or text(record.get("external_id")) or text(record.get("id"))


require_password()
if st.sidebar.button("Log out", key="commandcore_pipeline_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Pipeline + Follow-up")
st.caption("See where every deal sits, what needs follow-up now, and create the next action without leaving the CRM.")

deals = list_records("deals")
tasks = list_records("tasks")
open_tasks = [task for task in tasks if is_open_task(task)]
today = date.today()
overdue = [task for task in open_tasks if due_date(task) and due_date(task) < today]
due_today = [task for task in open_tasks if due_date(task) == today]
upcoming = [task for task in open_tasks if due_date(task) and due_date(task) > today]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Open deals", len(deals))
m2.metric("Overdue follow-ups", len(overdue))
m3.metric("Due today", len(due_today))
m4.metric("Upcoming", len(upcoming))

pipeline_tab, followup_tab = st.tabs(["Pipeline", "Follow-up Queue"])

with pipeline_tab:
    stages = sorted({text(deal.get("stage")) or "Unassigned Stage" for deal in deals})
    if not stages:
        st.info("No deals are in CommandCore yet.")
    else:
        columns = st.columns(min(len(stages), 5))
        for index, stage in enumerate(stages):
            with columns[index % len(columns)]:
                st.subheader(stage)
                stage_deals = [deal for deal in deals if (text(deal.get("stage")) or "Unassigned Stage") == stage]
                for deal in stage_deals:
                    with st.container(border=True):
                        st.markdown(f"**{deal_title(deal)}**")
                        st.caption(f"Owner: {text(deal.get('assigned_to')) or 'Unassigned'}")
                        asking = text(deal.get("asking_price"))
                        offer = text(deal.get("offer_price"))
                        if asking or offer:
                            st.caption(f"Ask: {asking or '—'}  |  Offer: {offer or '—'}")

    st.divider()
    st.subheader("Update deal stage")
    if deals:
        selected = st.selectbox("Deal", deals, format_func=deal_title)
        c1, c2 = st.columns(2)
        new_stage = c1.text_input("Stage", value=text(selected.get("stage")))
        new_status = c2.text_input("Status", value=text(selected.get("status")))
        if st.button("Save stage/status", type="primary"):
            result = upsert("deals", {**selected, "stage": new_stage, "status": new_status})
            if result.get("ok"):
                st.success("Deal pipeline updated.")
                st.rerun()
            st.error(text(result.get("error")) or "Could not update the deal.")

with followup_tab:
    st.subheader("Needs attention now")
    attention = sorted(overdue + due_today, key=lambda task: due_date(task) or today)
    if not attention:
        st.success("No overdue or due-today follow-ups.")
    for task in attention:
        task_due = due_date(task)
        links = task.get("links") if isinstance(task.get("links"), dict) else {}
        deal_id = text(links.get("deal_id") if isinstance(links, dict) else "")
        linked_deal = next((deal for deal in deals if text(deal.get("id")) == deal_id), None)
        with st.container(border=True):
            st.markdown(f"**{text(task.get('title')) or 'Follow up'}**")
            st.caption(
                f"Deal: {deal_title(linked_deal) if linked_deal else deal_id or 'Unlinked'}  |  "
                f"Due: {task_due.isoformat() if task_due else 'No date'}  |  "
                f"Owner: {text(task.get('assigned_to')) or 'Unassigned'}"
            )

    st.divider()
    st.subheader("Schedule next follow-up")
    if deals:
        chosen = st.selectbox("Deal for follow-up", deals, format_func=deal_title, key="followup_deal")
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
                st.success("Follow-up created. Due follow-ups are synced into the CommandCore Action Queue by the background service.")
                st.rerun()
            st.error(text(result.get("error")) or "Could not create the follow-up.")

st.divider()
st.caption("This workspace changes internal CRM records only. It does not send seller messages, make offers, sign contracts, move money, or perform external actions.")
