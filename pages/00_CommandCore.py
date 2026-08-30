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

with st.expander("Browse all CommandCore tools", expanded=False):
    area = st.selectbox(
        "Area",
        [
            "Home / Command Center",
            "Leads & CRM",
            "Deals",
            "Tasks & Follow-Up",
            "Marketing & Dispo",
            "Management",
        ],
        index=0,
        key="commandcore_tool_area",
    )

if area == "Home / Command Center":
    with st.container(border=True):
        st.markdown("### Command Bot")
        st.caption(
            "Tell CommandCore what you need in plain English. The safe version can create internal deal work "
            "for analysis, offer prep, contract/CFD prep, title/closing, and marketing/dispo."
        )
        st.page_link(
            "pages/49_CommandCore_Command_Bot.py",
            label="Open Command Bot",
            icon="🤖",
            use_container_width=True,
        )
        st.caption(
            "Command Bot cannot send, sign, approve, change legal terms, move money, or start an outside transaction."
        )

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

    st.markdown("### Start work")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        link(
            "pages/35_CommandCore_My_Work.py",
            "My Work",
            "Start with the work assigned to you, handoffs, and high-priority items.",
        )
    with c2:
        link(
            "pages/48_CommandCore_Owner_Approvals.py",
            "Owner Approvals",
            "Review consequential decisions before anything external can move forward.",
        )
    with c3:
        link(
            "pages/45_CommandCore_Deal_Record.py",
            "Open a Deal",
            "Work the seller, property, tasks, offers, documents, and history from one record.",
        )
    with c4:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Pipeline & Follow-Up",
            "Review open deals, overdue work, and today's follow-ups.",
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
    st.caption("The deal is the center of CommandCore. Open the Unified Deal Record first for day-to-day deal work.")

    st.markdown("### Start here")
    link(
        "pages/45_CommandCore_Deal_Record.py",
        "Unified Deal Record",
        "Work the seller, property, notes, tasks, communications, offers, documents, transactions, and complete history in one place.",
    )

    st.markdown("### Supporting deal views")
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Deal Pipeline",
            "See deal stages, follow-up timing, and open the exact deal from the pipeline.",
        )
    with c2:
        link(
            "pages/47_CommandCore_Deal_Workflow_Queue.py",
            "Deal Workflow",
            "See what each deal needs next and what information is missing.",
        )
    with c3:
        link(
            "pages/48_CommandCore_Owner_Approvals.py",
            "Owner Approvals",
            "Approve or reject owner-gated deal actions without starting external execution.",
        )

elif area == "Tasks & Follow-Up":
    st.subheader("Tasks & Follow-Up")
    st.caption("Start with My Work for assigned work. Use Follow-Up and Coverage when you need the broader queue or exceptions.")

    st.markdown("### Start here")
    link(
        "pages/35_CommandCore_My_Work.py",
        "My Work",
        "See assigned work, high-priority items, handoffs, shift briefs, and takeover tracking in one daily queue.",
    )

    st.markdown("### Supporting work views")
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/46_CommandCore_Pipeline_Followup.py",
            "Follow-Up Queue",
            "Review overdue, due-today, and upcoming CRM follow-ups and open the linked deal.",
        )
    with c2:
        link(
            "pages/36_CommandCore_Coverage.py",
            "Coverage",
            "Find missed handoffs and safely route uncovered internal work.",
        )
    with c3:
        link(
            "pages/21_CommandCore_Operator_Dashboard.py",
            "Team Queue",
            "Use the broader operator queue when you need team-level assignment and workload visibility.",
        )

elif area == "Marketing & Dispo":
    st.subheader("Marketing & Dispo")
    st.caption("Run property marketing, buyer movement, and disposition from one organized workspace.")

    st.markdown("### Start here")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        link(
            "pages/01_Record_Manager.py",
            "Property Records",
            "Manage the locked owner-finance property facts used by every channel.",
        )
    with c2:
        link(
            "pages/90_CFH_Marketing_Dispo.py",
            "Marketing Command",
            "Launch and manage the preserved Credit Friendly Homes marketing workflow.",
        )
    with c3:
        link(
            "pages/23_Daily_Executive_Disposition_Command.py",
            "Disposition Command",
            "Review property-level disposition performance and next actions.",
        )
    with c4:
        link(
            "pages/19_Dwelyx_Results_Attribution.py",
            "Buyer Results",
            "Review buyer traffic and attribution. Dwelyx live feed setup remains separate.",
        )

    st.markdown("### Buyer lifecycle")
    b1, b2, b3 = st.columns(3)
    with b1:
        link(
            "pages/29_Email_SMS_Reactivation.py",
            "Buyer Outreach",
            "Prepare consent-checked email and SMS handoffs.",
        )
        link(
            "pages/13_AI_Buyer_Reactivation_Autopilot.py",
            "Buyer Reactivation",
            "Re-engage eligible buyers with cooldowns, approvals, consent rechecks, and history.",
        )
    with b2:
        link(
            "pages/15_AI_Buyer_Acquisition_Growth.py",
            "Buyer Acquisition",
            "Build and measure campaigns that grow the owner-finance buyer pool.",
        )
        link(
            "pages/16_AI_Buyer_Conversion_Command_Center.py",
            "Buyer Conversion",
            "Move matched buyers through follow-up and conversion without creating work on unavailable homes.",
        )
    with b3:
        link(
            "pages/22_Showing_to_Contract_Conversion.py",
            "Showing to Contract",
            "Track appointments, reminders, outcomes, and the path from showing to signed contract.",
        )

    st.markdown("### Marketing channels")
    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        link(
            "pages/7_Facebook_Group_Posting_Center.py",
            "Facebook Groups",
            "Run the manual Facebook Group posting workflow with fact-safe property content.",
        )
        link(
            "pages/10_Facebook_Daily_Assignments.py",
            "Facebook Daily Assignments",
            "See daily group assignments, cooldowns, and team posting responsibilities.",
        )
    with ch2:
        link(
            "pages/26_Instagram_TikTok_YouTube_Shorts.py",
            "Social Video",
            "Build fact-locked Instagram, TikTok, and YouTube packages with an approved handoff.",
        )
        link(
            "pages/17_Nextdoor_Channel_15.py",
            "Nextdoor",
            "Prepare the manual-final-step Nextdoor property posting package.",
        )
    with ch3:
        link(
            "pages/27_Classifieds_Channel.py",
            "Classifieds",
            "Prepare compliant manual or platform-approved classified listings.",
        )
        link(
            "pages/30_Owned_Web_SEO_Channels.py",
            "Owned Web & SEO",
            "Use the CFH-owned Blog and Market SEO publishing paths.",
        )

    st.markdown("### Optimize, recover & refresh")
    o1, o2, o3 = st.columns(3)
    with o1:
        link(
            "pages/11_AI_Marketing_Optimizer.py",
            "Marketing Optimizer",
            "Use saved performance data to prioritize the next marketing improvements.",
        )
        link(
            "pages/14_AI_Creative_Winner_Rotation.py",
            "Creative Testing",
            "Test controlled fact-safe creative variations and approve winners.",
        )
    with o2:
        link(
            "pages/20_Vacant_Home_Disposition_Escalation.py",
            "Vacant Home Escalation",
            "Escalate stagnant vacant inventory using persisted campaign and buyer-response data.",
        )
        link(
            "pages/18_Property_Shutdown_Buyer_Reroute.py",
            "Property Shutdown & Reroute",
            "Stop marketing on unavailable inventory and reroute buyer work safely.",
        )
    with o3:
        link(
            "pages/24_15_Channel_Campaign_Cadence_Refresh.py",
            "Campaign Cadence & Refresh",
            "Manage refresh timing across the property marketing channels.",
        )
        link(
            "pages/25_Property_Channel_Tracking_Links.py",
            "Tracking Links",
            "Review channel-specific tracked links and attribution support.",
        )

    st.markdown("### Paid growth planning")
    st.caption("Planning only. Connecting ad accounts or spending money still requires owner authorization.")
    p1, p2 = st.columns(2)
    with p1:
        link(
            "pages/28_Meta_Google_Paid_Traffic.py",
            "Meta & Google Ads Plan",
            "Prepare fact-locked paid-traffic plans. No campaign or spend starts here.",
        )
    with p2:
        link(
            "pages/33_ChatGPT_Ads_Channel_16.py",
            "ChatGPT Ads Plan",
            "Prepare buyer-acquisition concepts without starting spend.",
        )

elif area == "Management":
    st.subheader("Management")
    st.caption("Operations, people, exceptions, audits, and system setup in one management workspace.")

    st.markdown("### Operations & people")
    c1, c2, c3 = st.columns(3)
    with c1:
        link(
            "pages/39_CommandCore_Operations_Hub.py",
            "Operations Hub",
            "See human-work escalations, operating readiness, and aged coverage failures first.",
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

    st.markdown("### System & setup")
    st.caption("Migration, connection status, completion audits, and diagnostics stay separate from daily work.")
    s1, s2 = st.columns(2)
    with s1:
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
    with s2:
        link(
            "pages/32_Go_Live_Connection_Center.py",
            "Go-Live Connections",
            "See sender, outreach, social, and paid-platform setup status without false readiness.",
        )
        link(
            "pages/34_Safe_Full_Payload_Test.py",
            "Safe Payload Diagnostic",
            "Run a controlled diagnostic without publishing, messaging, creating ads, or spending money.",
        )

st.divider()
st.caption(
    "This shell reorganizes existing CommandCore and CFH functionality. It does not expand approval authority, "
    "send communications, sign contracts, change legal terms, or move money."
)
