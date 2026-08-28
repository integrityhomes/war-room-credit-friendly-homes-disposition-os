from __future__ import annotations

from datetime import date, datetime
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore", page_icon="🧭", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore")
    with st.form("commandcore_shell_login"):
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


def list_records(entity: str) -> list[dict[str, Any]]:
    result = call_crm({"action": "list", "entity": entity, "limit": 500})
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def text(value: Any) -> str:
    return str(value or "").strip()


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


def open_task(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() not in {
        "done",
        "completed",
        "closed",
        "cancelled",
        "canceled",
    }


def active_deal(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() not in {
        "closed",
        "sold",
        "dead",
        "lost",
        "cancelled",
        "canceled",
        "archived",
    }


def link(path: str, label: str, caption: str = "") -> None:
    with st.container(border=True):
        st.page_link(path, label=label, use_container_width=True)
        if caption:
            st.caption(caption)


require_password()
if st.sidebar.button("Log out", key="commandcore_shell_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore")
st.caption("One operating system for leads, deals, follow-up, marketing, disposition, and management.")

st.markdown("### Command Bot")
st.text_input(
    "Tell CommandCore what you need",
    placeholder="Example: Prepare the CFD for 123 Main Street",
    disabled=True,
    help="Command Bot routing is reserved here and will be connected after the core operating flow is stable.",
)
st.caption("Command Bot is reserved in the primary workspace. It is not executing commands yet.")

st.divider()
area = st.segmented_control(
    "Workspace",
    [
        "Home / Command Center",
        "Leads & CRM",
        "Deals",
        "Tasks & Follow-Up",
        "Marketing & Dispo",
        "Management",
    ],
    default="Home / Command Center",
)
area = area or "Home / Command Center"

if area == "Home / Command Center":
    st.subheader("Today")
    st.caption("Start here. CommandCore surfaces the work and exceptions that matter now.")
    try:
        deals = [deal for deal in list_records("deals") if active_deal(deal)]
        tasks = [task for task in list_records("tasks") if open_task(task)]
        today = date.today()
        new_leads = [deal for deal in deals if text(deal.get("stage")).lower() == "new lead"]
        overdue = [task for task in tasks if due_date(task) and due_date(task) < today]
        due_today = [task for task in tasks if due_date(task) == today]
        high_priority = [task for task in tasks if text(task.get("priority")).lower() in {"high", "urgent", "critical"}]

        metrics = st.columns(5)
        metrics[0].metric("Active deals", len(deals))
        metrics[1].metric("New leads", len(new_leads))
        metrics[2].metric("Overdue", len(overdue))
        metrics[3].metric("Due today", len(due_today))
        metrics[4].metric("High priority", len(high_priority))

        if overdue or due_today or high_priority:
            st.warning(
                f"Needs attention: {len(overdue)} overdue, {len(due_today)} due today, "
                f"and {len(high_priority)} high-priority open task(s)."
            )
        else:
            st.success("No overdue, due-today, or high-priority CRM tasks are currently waiting.")
    except RuntimeError as exc:
        st.error(f"CommandCore home data could not be loaded: {exc}")

    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Pipeline & Follow-Up",
            "Open deals, overdue work, and today's follow-ups.",
        )
    with c2:
        link(
            "pages/45_CommandCore_Deal_Record.py",
            "Open a Deal",
            "Work the seller, property, tasks, offers, documents, and history from one record.",
        )
    with c3:
        link(
            "pages/44_CommandCore_CRM.py",
            "Leads & CRM",
            "Contacts, properties, and deal records.",
        )

elif area == "Leads & CRM":
    st.subheader("Leads & CRM")
    st.caption("Seller and agent leads, contacts, properties, and intake records.")
    c1, c2 = st.columns(2)
    with c1:
        link(
            "pages/44_CommandCore_CRM.py",
            "CRM Workspace",
            "Search, create, and update contacts, properties, and deals.",
        )
    with c2:
        link(
            "pages/43_CommandCore_CRM_Migration.py",
            "CRM Migration",
            "Stage, review, and safely import existing CRM records.",
        )

elif area == "Deals":
    st.subheader("Deals")
    st.caption("The deal is the center of CommandCore. Open one record and keep the entire transaction together.")
    c1, c2 = st.columns(2)
    with c1:
        link(
            "pages/45_CommandCore_Deal_Record.py",
            "Unified Deal Record",
            "Seller, property, notes, tasks, communications, offers, documents, transactions, and history.",
        )
    with c2:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Deal Pipeline",
            "See deal stages and move internal pipeline status forward.",
        )

elif area == "Tasks & Follow-Up":
    st.subheader("Tasks & Follow-Up")
    st.caption("What the team needs to do now, who owns it, and what is overdue.")
    link(
        "pages/46_CommandCore_Pipeline_Followup.py",
        "Follow-Up Queue",
        "Overdue, due-today, and upcoming CRM follow-ups.",
    )
    st.info(
        "Existing My Work, Action Queue, coverage, and escalation tools remain available in the current "
        "application while they are consolidated into this area."
    )

elif area == "Marketing & Dispo":
    st.subheader("Marketing & Dispo")
    st.caption(
        "The existing Credit Friendly Homes marketing and disposition engine remains intact while it is "
        "consolidated under this area."
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/01_Record_Manager.py",
            "Property Records",
            "Manage owner-finance property records used by marketing.",
        )
    with c2:
        link(
            "pages/19_Dwelyx_Results_Attribution.py",
            "Buyer & Dwelyx Results",
            "Review buyer traffic and attribution.",
        )
    with c3:
        link(
            "pages/23_Daily_Executive_Disposition_Command.py",
            "Disposition Command",
            "Open the existing executive disposition workspace.",
        )
    st.info(
        "The current 15/16-channel CFH tools are being preserved, not rebuilt. They will be grouped here in "
        "later shell passes."
    )

else:
    st.subheader("Management")
    st.caption("Operations visibility, workload, coverage, audits, migration, integrations, and settings.")
    c1, c2 = st.columns(2)
    with c1:
        link(
            "pages/43_CommandCore_CRM_Migration.py",
            "CRM Migration",
            "Controlled import and migration tools.",
        )
    with c2:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Pipeline Health",
            "Deal and follow-up operating visibility.",
        )
    st.info(
        "Existing Operations Hub, Team Health, Workload Balance, Rebalance Audit, Coverage, and Management "
        "Alerts remain active while their exact page routes are consolidated into this Management area."
    )

st.divider()
st.caption(
    "This shell reorganizes existing CommandCore and CFH functionality. It does not expand approval authority, "
    "send communications, sign contracts, change legal terms, or move money."
)
