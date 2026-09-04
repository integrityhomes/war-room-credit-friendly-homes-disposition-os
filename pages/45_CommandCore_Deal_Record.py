from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_contract_workspace_ui import render_contract_workspace
from cfh_disposition.commandcore_deal_summary import build_deal_summary, next_open_task, status_label
from cfh_disposition.commandcore_followup import MAX_FOLLOWUP_NOTE_LENGTH, build_followup_record
from cfh_disposition.commandcore_offer_workspace_ui import render_offer_workspace
from supabase import create_client

st.set_page_config(page_title="CommandCore Deal Record", page_icon="📂", layout="wide")

RELATED_ENTITIES = ["activities", "communications", "tasks", "offers", "documents", "transactions"]
DEAL_TAB_LABELS = [
    "Overview",
    "Next Step",
    "Tasks",
    "Messages",
    "Offers & Approval",
    "Documents & Closing",
    "History",
]


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Deal Record")
    with st.form("commandcore_deal_login"):
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


def linked_record(entity: str, record_id: str) -> dict[str, Any] | None:
    if not record_id:
        return None
    result = call_crm({"action": "get", "entity": entity, "id": record_id})
    record = result.get("record")
    return record if isinstance(record, dict) else None


def related_to_deal(record: dict[str, Any], deal_id: str) -> bool:
    return text(links(record).get("deal_id")) == deal_id or text(record.get("deal_id")) == deal_id


def save_related(entity: str, deal_id: str, record: dict[str, Any]) -> bool:
    record_links = links(record)
    payload = {**record, "links": {**record_links, "deal_id": deal_id}}
    result = call_crm({"action": "upsert", "entity": entity, "record": payload})
    return bool(result.get("ok"))


def upsert_record(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    result = call_crm({"action": "upsert", "entity": entity, "record": record})
    saved = result.get("record")
    return saved if isinstance(saved, dict) else {}


def deal_label(deal: dict[str, Any]) -> str:
    return text(deal.get("title")) or text(deal.get("stage")) or text(deal.get("id"))


def show_related_table(entity: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.caption(f"No {entity} yet.")
        return
    preferred = {
        "tasks": ["title", "status", "assigned_to", "due_at", "due_date", "updated_at"],
        "communications": ["channel", "direction", "summary", "status", "created_at"],
        "offers": ["amount", "status", "terms", "created_at"],
        "documents": ["name", "document_type", "version", "status", "created_at"],
        "transactions": ["transaction_type", "amount", "status", "created_at"],
        "activities": ["activity_type", "summary", "created_at"],
    }
    columns = preferred.get(entity, [])
    table = [{column: row.get(column) for column in columns if column in row} for row in rows]
    st.dataframe(table, use_container_width=True, hide_index=True)


def open_task_exists(rows: list[dict[str, Any]], work_type: str) -> bool:
    for row in rows:
        status = text(row.get("status")).lower()
        if text(row.get("work_type")) == work_type and status not in {
            "done",
            "completed",
            "closed",
            "cancelled",
            "canceled",
        }:
            return True
    return False


def create_work_request(
    deal: dict[str, Any],
    deal_id: str,
    related_tasks: list[dict[str, Any]],
    work_type: str,
    title: str,
) -> None:
    if open_task_exists(related_tasks, work_type):
        st.info(f"An open '{title}' request already exists for this deal.")
        return
    saved = save_related(
        "tasks",
        deal_id,
        {
            "title": title,
            "work_type": work_type,
            "task_type": "deal_lifecycle_request",
            "status": "open",
            "priority": "high" if work_type in {"prepare_offer", "prepare_contract", "title_closing"} else "medium",
            "assigned_to": text(deal.get("assigned_to")) or None,
            "source": "commandcore-deal-record",
        },
    )
    if saved:
        st.success(f"{title} request added to the deal.")
        st.rerun()
    st.error("CommandCore could not create the work request.")


def open_deal_tab(label: str) -> None:
    if label not in DEAL_TAB_LABELS:
        return
    st.session_state["commandcore_deal_pending_tab"] = label
    st.rerun()


def open_marketing(property_record: dict[str, Any]) -> None:
    property_id = text(property_record.get("id") or property_record.get("property_id"))
    address = text(property_record.get("display_address") or property_record.get("address"))
    if property_id:
        st.session_state["commandcore_marketing_property_id"] = property_id
    if address:
        st.session_state["commandcore_marketing_property_address"] = address
    st.session_state["pending_main_navigation"] = "Marketing Home"
    st.switch_page("pages/90_CFH_Marketing_Dispo.py")


require_password()
if st.sidebar.button("Log out", key="commandcore_deal_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Unified Deal Record")
st.caption(
    "Open one deal and see the seller, property, tasks, communications, offers, documents, transactions, "
    "and activity history together."
)

deals = list_records("deals")
if not deals:
    with st.container(border=True):
        st.markdown("### No deals yet")
        st.write(
            "Start with one lead. CommandCore will create and link the seller, property, and deal, then bring you back here automatically."
        )
        if st.button("Add Your First Lead", type="primary", use_container_width=True):
            st.switch_page("pages/44_CommandCore_CRM.py")
        st.caption("You do not need to create separate seller, property, and deal records manually.")
    st.stop()

deal_options = {deal_label(deal): deal for deal in deals}
deal_labels = list(deal_options)
requested_deal_id = text(st.session_state.get("commandcore_selected_deal_id"))
default_index = next(
    (
        index
        for index, label in enumerate(deal_labels)
        if text(deal_options[label].get("id")) == requested_deal_id
    ),
    0,
)
selected_label = st.selectbox("Open deal", deal_labels, index=default_index)
deal = deal_options[selected_label]
deal_id = text(deal.get("id"))
st.session_state["commandcore_selected_deal_id"] = deal_id
deal_links = links(deal)

seller = linked_record("contacts", text(deal_links.get("contact_id")))
property_record = linked_record("properties", text(deal_links.get("property_id")))

st.subheader(deal_label(deal))
summary_cols = st.columns(5)
summary_cols[0].metric("Stage", text(deal.get("stage")) or "—")
summary_cols[1].metric("Status", text(deal.get("status")) or "—")
summary_cols[2].metric("Asking", text(deal.get("asking_price")) or "—")
summary_cols[3].metric("Our offer", text(deal.get("offer_price")) or "—")
summary_cols[4].metric("Assigned to", text(deal.get("assigned_to")) or "—")

seller_col, property_col = st.columns(2)
with seller_col:
    st.markdown("### Seller")
    if seller:
        seller_name = text(seller.get("name")) or " ".join(
            filter(None, [text(seller.get("first_name")), text(seller.get("last_name"))])
        )
        st.write(seller_name)
        st.caption(" • ".join(filter(None, [text(seller.get("phone")), text(seller.get("email"))])))
        if text(seller.get("notes")):
            st.write(text(seller.get("notes")))
    else:
        st.caption("No seller is linked to this deal yet.")
with property_col:
    st.markdown("### Property")
    if property_record:
        st.write(text(property_record.get("address")) or "Property")
        location = ", ".join(
            filter(
                None,
                [
                    text(property_record.get("city")),
                    text(property_record.get("state")),
                    text(property_record.get("zip")),
                ],
            )
        )
        st.caption(location)
        facts = " • ".join(
            filter(
                None,
                [
                    f"{text(property_record.get('bedrooms'))} bd" if text(property_record.get("bedrooms")) else "",
                    f"{text(property_record.get('bathrooms'))} ba" if text(property_record.get("bathrooms")) else "",
                    f"{text(property_record.get('square_feet'))} sqft"
                    if text(property_record.get("square_feet"))
                    else "",
                ],
            )
        )
        if facts:
            st.write(facts)
    else:
        st.caption("No property is linked to this deal yet.")

st.divider()
related = {
    entity: [record for record in list_records(entity) if related_to_deal(record, deal_id)]
    for entity in RELATED_ENTITIES
}
deal_summary = build_deal_summary(related)

pending_tab = text(st.session_state.pop("commandcore_deal_pending_tab", ""))
if pending_tab in DEAL_TAB_LABELS:
    st.session_state["commandcore_deal_tabs"] = pending_tab
overview, next_step_tab, tasks_tab, messages_tab, offers_tab, closing_tab, history_tab = st.tabs(
    DEAL_TAB_LABELS,
    key="commandcore_deal_tabs",
)

with overview:
    st.markdown("### Deal at a glance")
    owner = text(deal.get("assigned_to")) or "Not assigned"
    next_task = deal_summary.next_task
    next_task_label = text(next_task.get("title")) if next_task else "No open task"
    next_task_due = text(next_task.get("due_at") or next_task.get("due_date")) if next_task else ""
    latest_message = deal_summary.recent_communication
    latest_activity = deal_summary.recent_activity

    headline = st.columns(3)
    headline[0].metric("Deal owner", owner)
    headline[1].metric("Next task / follow-up", next_task_label)
    headline[1].caption(f"Due: {next_task_due}" if next_task_due else "No due date recorded")
    headline[2].metric("Approvals needing attention", deal_summary.approval_count)
    if deal_summary.approval_count:
        headline[2].page_link(
            "pages/48_CommandCore_Owner_Approvals.py",
            label="Review owner approvals",
            use_container_width=True,
        )

    recent = st.columns(2)
    with recent[0]:
        st.markdown("#### Latest communication")
        if latest_message:
            st.write(text(latest_message.get("summary")) or "Communication recorded; no summary provided.")
            st.caption(
                " • ".join(
                    filter(
                        None,
                        [
                            text(latest_message.get("channel")).title(),
                            text(latest_message.get("direction")).title(),
                            text(latest_message.get("created_at") or latest_message.get("updated_at")),
                        ],
                    )
                )
                or "Details not recorded"
            )
        else:
            st.caption("No communication recorded for this deal yet.")
    with recent[1]:
        st.markdown("#### Latest activity")
        if latest_activity:
            st.write(text(latest_activity.get("summary")) or "Activity recorded; no summary provided.")
            st.caption(
                " • ".join(
                    filter(
                        None,
                        [
                            text(latest_activity.get("activity_type")).replace("_", " ").title(),
                            text(latest_activity.get("created_at") or latest_activity.get("updated_at")),
                        ],
                    )
                )
                or "Details not recorded"
            )
        else:
            st.caption("No activity recorded for this deal yet.")

    st.markdown("#### Deal progress")
    progress = st.columns(4)
    progress[0].metric("Offer", status_label(deal_summary.offer))
    progress[1].metric("Contract / documents", status_label(deal_summary.document))
    progress[2].metric("Title / closing", status_label(deal_summary.closing))
    progress[3].metric("Marketing / disposition", status_label(deal_summary.marketing))

    st.markdown("#### Quick actions")
    st.caption("Open the existing workflow for this Deal. These actions do not send, approve, sign, or publish anything.")
    action_columns = st.columns(4)
    action_index = 0

    if next_task and action_columns[action_index % 4].button(
        "View Next Task",
        key=f"deal_quick_task_{deal_id}",
        use_container_width=True,
    ):
        open_deal_tab("Tasks")
    if next_task:
        action_index += 1

    if latest_message and action_columns[action_index % 4].button(
        "View Communications",
        key=f"deal_quick_messages_{deal_id}",
        use_container_width=True,
    ):
        open_deal_tab("Messages")
    if latest_message:
        action_index += 1

    if latest_activity and action_columns[action_index % 4].button(
        "View Recent Activity",
        key=f"deal_quick_history_{deal_id}",
        use_container_width=True,
    ):
        open_deal_tab("History")
    if latest_activity:
        action_index += 1

    offer_action = "Review Offers" if deal_summary.offer else "Start Offer Review"
    if action_columns[action_index % 4].button(
        offer_action,
        key=f"deal_quick_offer_{deal_id}",
        use_container_width=True,
    ):
        open_deal_tab("Offers & Approval")
    action_index += 1

    if action_columns[action_index % 4].button(
        "Open Documents & Closing",
        key=f"deal_quick_closing_{deal_id}",
        use_container_width=True,
    ):
        open_deal_tab("Documents & Closing")
    action_index += 1

    if property_record and action_columns[action_index % 4].button(
        "Open Marketing",
        key=f"deal_quick_marketing_{deal_id}",
        use_container_width=True,
    ):
        open_marketing(property_record)
    if property_record:
        action_index += 1
    else:
        st.caption("Marketing will be available after a property is linked to this Deal.")

    if deal_summary.approval_count:
        action_columns[action_index % 4].page_link(
            "pages/48_CommandCore_Owner_Approvals.py",
            label="Review Approval",
            use_container_width=True,
        )

    st.divider()
    st.markdown("### Deal notes")
    st.write(text(deal.get("notes")) or "No deal notes yet.")
    stats = st.columns(6)
    stats[0].metric("Tasks", len(related["tasks"]))
    stats[1].metric("Messages", len(related["communications"]))
    stats[2].metric("Offers", len(related["offers"]))
    stats[3].metric("Documents", len(related["documents"]))
    stats[4].metric("Closing / Transactions", len(related["transactions"]))
    stats[5].metric("History", len(related["activities"]))
    with st.form("quick_activity"):
        note = st.text_area("Add internal deal note", height=90)
        if st.form_submit_button("Save note", type="primary") and note.strip():
            saved = save_related(
                "activities",
                deal_id,
                {"activity_type": "note", "summary": note.strip(), "source": "commandcore"},
            )
            if saved:
                st.success("Note saved to the deal history.")
                st.rerun()
            st.error("CommandCore could not save the note.")

with next_step_tab:
    st.markdown("### What should happen next?")
    st.caption(
        "Start the next internal work from this deal. These buttons create tracked work requests only; they do "
        "not send offers, sign contracts, change legal terms, spend money, or contact outside parties."
    )
    stage = text(deal.get("stage")) or "New Lead"
    st.info(f"Current pipeline stage: **{stage}**")
    st.info("Need to analyze the deal? Open **Offers & Approval** and choose **Analyze Deal**. That is the single Deal Analysis workflow.")
    first_row = st.columns(2)
    if first_row[0].button("Request Offer Prep", use_container_width=True):
        create_work_request(deal, deal_id, related["tasks"], "prepare_offer", "Prepare offer for approval")
    if first_row[1].button("Request Contract Prep", use_container_width=True):
        create_work_request(
            deal,
            deal_id,
            related["tasks"],
            "prepare_contract",
            "Prepare contract package for approval",
        )
    second_row = st.columns(2)
    if second_row[0].button("Request Title / Closing Work", use_container_width=True):
        create_work_request(
            deal,
            deal_id,
            related["tasks"],
            "title_closing",
            "Review title and closing requirements",
        )
    if second_row[1].button("Request Marketing / Dispo", use_container_width=True):
        create_work_request(
            deal,
            deal_id,
            related["tasks"],
            "marketing_dispo",
            "Prepare marketing and disposition handoff",
        )

    lifecycle_rows = [
        task
        for task in related["tasks"]
        if text(task.get("task_type")) == "deal_lifecycle_request"
    ]
    st.markdown("### Work already started")
    show_related_table("tasks", lifecycle_rows)

with tasks_tab:
    followups = [task for task in related["tasks"] if text(task.get("task_type")) == "crm_follow_up"]
    next_followup = next_open_task(followups)
    st.markdown("### Next follow-up")
    if next_followup:
        st.write(text(next_followup.get("title")) or "Follow up")
        st.caption(
            " • ".join(
                [
                    f"Due: {text(next_followup.get('due_at') or next_followup.get('due_date')) or 'Not scheduled'}",
                    f"Assigned to: {text(next_followup.get('assigned_to')) or 'Unassigned'}",
                ]
            )
        )
    else:
        st.caption("No open follow-up is scheduled for this Deal.")

    st.markdown("### Schedule follow-up")
    st.caption("This creates an internal task only. It does not send a message or make a call.")
    with st.form("deal_followup"):
        note = st.text_input(
            "Follow-up note",
            placeholder="Example: Call seller to confirm the inspection date",
            max_chars=MAX_FOLLOWUP_NOTE_LENGTH,
        )
        due_columns = st.columns(2)
        followup_date = due_columns[0].date_input("Due date", value=date.today())
        followup_time = due_columns[1].time_input("Due time", value=time(hour=9))
        owner = st.text_input(
            "Assigned to",
            value=text(deal.get("assigned_to")),
            help="The current Deal owner is preserved unless you deliberately change this field.",
        )
        submitted = st.form_submit_button("Schedule Follow-Up", type="primary", use_container_width=True)
    if submitted:
        try:
            record = build_followup_record(
                deal_id=deal_id,
                note=note,
                due=datetime.combine(followup_date, followup_time),
                assigned_to=owner,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            saved = save_related("tasks", deal_id, record)
            if saved:
                st.success("Follow-up scheduled. No message or call was made.")
                st.rerun()
            st.error("CommandCore could not schedule the follow-up. Your existing tasks were not changed.")

    st.markdown("### All Deal tasks")
    show_related_table("tasks", related["tasks"])

with messages_tab:
    st.caption(
        "Communication history is shown here. Sending remains controlled by the communication/approval workflows."
    )
    show_related_table("communications", related["communications"])

with offers_tab:
    render_offer_workspace(
        st,
        deal=deal,
        deal_id=deal_id,
        property_record=property_record,
        upsert_record=upsert_record,
        save_related=save_related,
    )
    st.divider()
    st.page_link(
        "pages/48_CommandCore_Owner_Approvals.py",
        label="Open Owner Approvals",
        use_container_width=True,
    )
    st.markdown("### Saved offers & analyses")
    show_related_table("offers", related["offers"])

with closing_tab:
    render_contract_workspace(
        deal=deal,
        deal_id=deal_id,
        documents=related["documents"],
        tasks=related["tasks"],
        save_related=save_related,
        create_work_request=create_work_request,
        get_supabase=get_supabase,
    )
    st.markdown("### All Documents")
    show_related_table("documents", related["documents"])
    st.markdown("### Closing / Transactions")
    show_related_table("transactions", related["transactions"])

with history_tab:
    st.markdown("### Complete activity history")
    show_related_table("activities", related["activities"])

st.divider()
st.caption(
    "This view organizes internal CRM information and tracked work requests only. It does not send messages, "
    "approve offers, sign contracts, change legal terms, or move money."
)
