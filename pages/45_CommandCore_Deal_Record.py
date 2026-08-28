from __future__ import annotations

from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Deal Record", page_icon="📂", layout="wide")

RELATED_ENTITIES = ["activities", "communications", "tasks", "offers", "documents", "transactions"]


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
    payload = {
        **record,
        "links": {**record_links, "deal_id": deal_id},
    }
    result = call_crm({"action": "upsert", "entity": entity, "record": payload})
    return bool(result.get("ok"))


def deal_label(deal: dict[str, Any]) -> str:
    return text(deal.get("title")) or text(deal.get("stage")) or text(deal.get("id"))


def show_related_table(entity: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        st.caption(f"No {entity} yet.")
        return
    preferred = {
        "tasks": ["title", "status", "assigned_to", "due_at", "updated_at"],
        "communications": ["channel", "direction", "summary", "status", "created_at"],
        "offers": ["amount", "status", "terms", "created_at"],
        "documents": ["name", "document_type", "status", "created_at"],
        "transactions": ["transaction_type", "amount", "status", "created_at"],
        "activities": ["activity_type", "summary", "created_at"],
    }
    columns = preferred.get(entity, [])
    table = [{column: row.get(column) for column in columns if column in row} for row in rows]
    st.dataframe(table, use_container_width=True, hide_index=True)


require_password()
if st.sidebar.button("Log out", key="commandcore_deal_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Unified Deal Record")
st.caption("Open one deal and see the seller, property, tasks, communications, offers, documents, transactions, and activity history together.")

deals = list_records("deals")
if not deals:
    st.info("No active deals are in CommandCore CRM yet.")
    st.stop()

deal_options = {deal_label(deal): deal for deal in deals}
selected_label = st.selectbox("Open deal", list(deal_options))
deal = deal_options[selected_label]
deal_id = text(deal.get("id"))
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
        st.write(text(seller.get("name")) or " ".join(filter(None, [text(seller.get("first_name")), text(seller.get("last_name"))])))
        st.caption(" • ".join(filter(None, [text(seller.get("phone")), text(seller.get("email"))])))
        if text(seller.get("notes")):
            st.write(text(seller.get("notes")))
    else:
        st.caption("No seller is linked to this deal yet.")
with property_col:
    st.markdown("### Property")
    if property_record:
        st.write(text(property_record.get("address")) or "Property")
        location = ", ".join(filter(None, [text(property_record.get("city")), text(property_record.get("state")), text(property_record.get("zip"))]))
        st.caption(location)
        facts = " • ".join(
            filter(
                None,
                [
                    f"{text(property_record.get('bedrooms'))} bd" if text(property_record.get("bedrooms")) else "",
                    f"{text(property_record.get('bathrooms'))} ba" if text(property_record.get("bathrooms")) else "",
                    f"{text(property_record.get('square_feet'))} sqft" if text(property_record.get("square_feet")) else "",
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

overview, tasks_tab, communications_tab, offers_tab, documents_tab, history_tab = st.tabs(
    ["Overview", "Tasks", "Communications", "Offers", "Documents", "History"]
)

with overview:
    st.markdown("### Deal notes")
    st.write(text(deal.get("notes")) or "No deal notes yet.")
    stats = st.columns(6)
    stats[0].metric("Tasks", len(related["tasks"]))
    stats[1].metric("Communications", len(related["communications"]))
    stats[2].metric("Offers", len(related["offers"]))
    stats[3].metric("Documents", len(related["documents"]))
    stats[4].metric("Transactions", len(related["transactions"]))
    stats[5].metric("Activities", len(related["activities"]))
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

with tasks_tab:
    with st.form("new_task"):
        title = st.text_input("Task")
        owner = st.text_input("Assigned to")
        due = st.text_input("Due date/time", placeholder="2026-08-30 09:00")
        if st.form_submit_button("Add task", type="primary") and title.strip():
            saved = save_related(
                "tasks",
                deal_id,
                {
                    "title": title.strip(),
                    "assigned_to": owner.strip(),
                    "due_at": due.strip(),
                    "status": "open",
                    "source": "commandcore",
                },
            )
            if saved:
                st.success("Task added.")
                st.rerun()
            st.error("CommandCore could not add the task.")
    show_related_table("tasks", related["tasks"])

with communications_tab:
    st.caption("Communication history is shown here. Sending remains controlled by the communication/approval workflows.")
    show_related_table("communications", related["communications"])

with offers_tab:
    show_related_table("offers", related["offers"])

with documents_tab:
    show_related_table("documents", related["documents"])

with history_tab:
    st.markdown("### Activities")
    show_related_table("activities", related["activities"])
    st.markdown("### Transactions")
    show_related_table("transactions", related["transactions"])

st.divider()
st.caption("This view organizes internal CRM information only. It does not send messages, approve offers, sign contracts, change legal terms, or move money.")
