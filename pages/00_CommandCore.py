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


def pending_owner_approval(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() in {
        "draft_pending_owner_approval",
        "needs_owner_approval",
        "owner_approval_required",
        "needs_approved_legal_template",
        "internal_review_ready",
    }


def open_lifecycle_work(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() not in {
        "completed",
        "done",
        "closed",
        "cancelled",
        "canceled",
        "owner_rejected",
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

with st.container(border=True):
    st.markdown("### Command Bot")
    st.caption(
        "Tell CommandCore what you need in plain English. The current safe version can create internal deal work "
        "for analysis, offer prep, contract/CFD prep, title/closing, and marketing/dispo."
    )
    st.page_link(
        "pages/49_CommandCore_Command_Bot.py",
        label="Open Command Bot",
        icon="🤖",
        use_container_width=True,
    )
    st.caption("Command Bot cannot send, sign, approve, change legal terms, move money, or start an outside transaction.")

st.divider()
area = st.segmented_control(
    "Workspace",
    [
        "Home / Command Center",
        "Leads & CRM",
        "Deals",
        "Tasks & Follow-Up",
        "Marketing & Dispo",
        "Marketing Planning",
        "Management",
        "System & Setup",
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
        offers = [record for record in list_records("offers") if pending_owner_approval(record)]
        documents = [record for record in list_records("documents") if pending_owner_approval(record)]
        lifecycle = [
            record
            for record in list_records("tasks")
            if open_lifecycle_work(record) and text(record.get("task_type")).startswith("deal_")
        ]
        today = date.today()
        new_leads = [deal for deal in deals if text(deal.get("stage")).lower() == "new lead"]
        overdue = [task for task in tasks if due_date(task) and due_date(task) < today]
        due_today = [task for task in tasks if due_date(task) == today]
        high_priority = [
            task
            for task in tasks
            if text(task.get("priority")).lower() in {"high", "urgent", "critical"}
        ]
        approvals = len(offers) + len(documents)

        metrics = st.columns(6)
        metrics[0].metric("Active deals", len(deals))
        metrics[1].metric("New leads", len(new_leads))
        metrics[2].metric("Overdue", len(overdue))
        metrics[3].metric("Due today", len(due_today))
        metrics[4].metric("Owner approvals", approvals)
        metrics[5].metric("Deal workflow", len(lifecycle))

        if approvals:
            st.error(f"Owner decision required: {approvals} approval item(s) are waiting.")
        elif overdue or due_today or high_priority:
            st.warning(
                f"Needs attention: {len(overdue)} overdue, {len(due_today)} due today, "
                f"and {len(high_priority)} high-priority open task(s)."
            )
        else:
            st.success("No owner approvals, overdue, due-today, or high-priority CRM tasks are currently waiting.")
    except RuntimeError as exc:
        st.error(f"CommandCore home data could not be loaded: {exc}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        link(
            "pages/48_CommandCore_Owner_Approvals.py",
            "Owner Approvals",
            "Review consequential decisions before anything external can move forward.",
        )
    with c2:
        link(
            "pages/47_CommandCore_Deal_Workflow_Queue.py",
            "Deal Workflow",
            "See analysis, offer, contract, title, closing, and dispo work moving through the system.",
        )
    with c3:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Pipeline & Follow-Up",
            "Open deals, overdue work, and today's follow-ups.",
        )
    with c4:
        link(
            "pages/45_CommandCore_Deal_Record.py",
            "Open a Deal",
            "Work the seller, property, tasks, offers, documents, and history from one record.",
        )

elif area == "Leads & CRM":
    st.subheader("Leads & CRM")
    st.caption("Seller and agent leads, contacts, properties, and intake records.")
    link(
        "pages/44_CommandCore_CRM.py",
        "CRM Workspace",
        "Search, create, and update contacts, properties, and deals.",
    )

elif area == "Deals":
    st.subheader("Deals")
    st.caption("The deal is the center of CommandCore. Open one record and keep the entire transaction together.")
    c1, c2, c3, c4 = st.columns(4)
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
    with c3:
        link(
            "pages/47_CommandCore_Deal_Workflow_Queue.py",
            "Deal Workflow",
            "See what each deal needs next and what information is missing.",
        )
    with c4:
        link(
            "pages/48_CommandCore_Owner_Approvals.py",
            "Owner Approvals",
            "Approve or reject owner-gated deal actions without starting external execution.",
        )

elif area == "Tasks & Follow-Up":
    st.subheader("Tasks & Follow-Up")
    st.caption("What the team needs to do now, who owns it, and what is overdue.")
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/35_CommandCore_My_Work.py",
            "My Work",
            "Assigned work, handoffs, shift briefs, and takeover tracking.",
        )
    with c2:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Follow-Up Queue",
            "Overdue, due-today, and upcoming CRM follow-ups.",
        )
    with c3:
        link(
            "pages/36_CommandCore_Coverage.py",
            "Coverage",
            "Find missed handoffs and safely route uncovered internal work.",
        )

elif area == "Marketing & Dispo":
    st.subheader("Marketing & Dispo")
    st.caption("Property marketing, buyer outreach, social promotion, attribution, and disposition.")
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/90_CFH_Marketing_Dispo.py",
            "Marketing Command",
            "Open the preserved Credit Friendly Homes marketing and launch workspace.",
        )
        link(
            "pages/29_Email_SMS_Reactivation.py",
            "Buyer Outreach",
            "Prepare and, when approved connections exist, hand off consent-checked buyer outreach.",
        )
    with c2:
        link(
            "pages/01_Record_Manager.py",
            "Property Records",
            "Manage owner-finance property records used by marketing.",
        )
        link(
            "pages/26_Instagram_TikTok_YouTube_Shorts.py",
            "Social Video",
            "Build fact-locked Instagram, TikTok, and YouTube packages with an approved manual or adapter handoff.",
        )
    with c3:
        link(
            "pages/23_Daily_Executive_Disposition_Command.py",
            "Disposition Command",
            "Open the executive disposition workspace.",
        )
        link(
            "pages/19_Dwelyx_Results_Attribution.py",
            "Buyer & Dwelyx Results",
            "Review buyer traffic and attribution.",
        )

elif area == "Marketing Planning":
    st.subheader("Marketing Planning")
    st.caption("Prepare paid acquisition plans without creating campaigns or authorizing spend.")
    c1, c2 = st.columns(2)
    with c1:
        link(
            "pages/28_Meta_Google_Paid_Traffic.py",
            "Meta & Google Ads Plan",
            "Prepare fact-locked housing/search ad plans. Budgets remain proposed until owner approval.",
        )
    with c2:
        link(
            "pages/33_ChatGPT_Ads_Channel_16.py",
            "ChatGPT Ads Plan",
            "Prepare buyer-acquisition campaign concepts for current Ads Manager workflows without starting spend.",
        )

elif area == "Management":
    st.subheader("Management")
    st.caption("Operations visibility, workload, coverage, audits, and exceptions.")
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/39_CommandCore_Operations_Hub.py",
            "Operations Hub",
            "See human-work escalations and aged coverage failures first.",
        )
        link(
            "pages/38_CommandCore_Management_Alerts.py",
            "Management Alerts",
            "Review management-level alerts and exceptions.",
        )
    with c2:
        link(
            "pages/40_CommandCore_Team_Health.py",
            "Team Health",
            "See team capacity and workload health.",
        )
        link(
            "pages/41_CommandCore_Workload_Balance.py",
            "Workload Balance",
            "Review safe internal balancing recommendations.",
        )
    with c3:
        link(
            "pages/37_CommandCore_Coverage_Exceptions.py",
            "Coverage Exceptions",
            "Review unresolved coverage failures.",
        )
        link(
            "pages/42_CommandCore_Rebalance_Audit.py",
            "Rebalance Audit",
            "See automatic internal workload moves and skipped actions.",
        )

else:
    st.subheader("System & Setup")
    st.caption("Migration, launch readiness, connection status, and diagnostics kept separate from daily work.")
    c1, c2 = st.columns(2)
    with c1:
        link(
            "pages/43_CommandCore_CRM_Migration.py",
            "CRM Migration",
            "Stage, review, and safely import existing CRM records.",
        )
        link(
            "pages/31_16_Channel_Completion_Audit.py",
            "Marketing Completion Audit",
            "See which marketing channels are usable now and which are externally blocked.",
        )
    with c2:
        link(
            "pages/32_Go_Live_Connection_Center.py",
            "Go-Live Connections",
            "See actual sender, outreach, social, and paid-platform setup status without false readiness.",
        )
        link(
            "pages/34_Safe_Full_Payload_Test.py",
            "Safe Payload Diagnostic",
            "Run a controlled test payload without publishing, messaging, creating ads, or spending money.",
        )

st.divider()
st.caption(
    "This shell reorganizes existing CommandCore and CFH functionality. It does not expand approval authority, "
    "send communications, sign contracts, change legal terms, or move money."
)
