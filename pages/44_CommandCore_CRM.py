from __future__ import annotations

from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore CRM", page_icon="🏠", layout="wide")

ENTITY_LABELS = {"contacts": "Contacts", "properties": "Properties", "deals": "Deals"}


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore CRM")
    with st.form("commandcore_crm_login"):
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


def load_records(entity: str) -> list[dict[str, Any]]:
    result = call_crm({"action": "list", "entity": entity, "limit": 500})
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def save_record(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    return call_crm({"action": "upsert", "entity": entity, "record": record})


def record_label(entity: str, record: dict[str, Any]) -> str:
    if entity == "contacts":
        return text(record.get("name")) or " ".join(
            part for part in [text(record.get("first_name")), text(record.get("last_name"))] if part
        ) or text(record.get("phone")) or text(record.get("email")) or text(record.get("id"))
    if entity == "properties":
        address = text(record.get("address"))
        location = ", ".join(part for part in [text(record.get("city")), text(record.get("state"))] if part)
        return f"{address} — {location}" if location else address or text(record.get("id"))
    return text(record.get("title")) or text(record.get("stage")) or text(record.get("id"))


def contact_form(existing: dict[str, Any]) -> dict[str, Any] | None:
    with st.form("crm_contact_form"):
        left, right = st.columns(2)
        first = left.text_input("First name", value=text(existing.get("first_name")))
        last = right.text_input("Last name", value=text(existing.get("last_name")))
        phone = left.text_input("Phone", value=text(existing.get("phone")))
        email = right.text_input("Email", value=text(existing.get("email")))
        company = st.text_input("Company", value=text(existing.get("company")))
        notes = st.text_area("Notes", value=text(existing.get("notes")), height=120)
        if st.form_submit_button("Save contact", type="primary"):
            return {**existing, "first_name": first, "last_name": last, "name": f"{first} {last}".strip(), "phone": phone, "email": email, "company": company, "notes": notes}
    return None


def property_form(existing: dict[str, Any]) -> dict[str, Any] | None:
    with st.form("crm_property_form"):
        address = st.text_input("Property address", value=text(existing.get("address")))
        c1, c2, c3 = st.columns(3)
        city = c1.text_input("City", value=text(existing.get("city")))
        state = c2.text_input("State", value=text(existing.get("state")))
        zip_code = c3.text_input("ZIP", value=text(existing.get("zip")))
        c4, c5, c6 = st.columns(3)
        beds = c4.text_input("Bedrooms", value=text(existing.get("bedrooms")))
        baths = c5.text_input("Bathrooms", value=text(existing.get("bathrooms")))
        sqft = c6.text_input("Square feet", value=text(existing.get("square_feet")))
        parcel = st.text_input("Parcel / APN", value=text(existing.get("parcel_id")))
        notes = st.text_area("Property notes", value=text(existing.get("notes")), height=120)
        if st.form_submit_button("Save property", type="primary"):
            return {**existing, "address": address, "city": city, "state": state, "zip": zip_code, "bedrooms": beds, "bathrooms": baths, "square_feet": sqft, "parcel_id": parcel, "notes": notes}
    return None


def deal_form(existing: dict[str, Any]) -> dict[str, Any] | None:
    with st.form("crm_deal_form"):
        title = st.text_input("Deal / lead name", value=text(existing.get("title")))
        c1, c2, c3 = st.columns(3)
        status = c1.text_input("Status", value=text(existing.get("status")))
        stage = c2.text_input("Pipeline stage", value=text(existing.get("stage")))
        owner = c3.text_input("Assigned to", value=text(existing.get("assigned_to")))
        c4, c5, c6 = st.columns(3)
        asking = c4.text_input("Asking price", value=text(existing.get("asking_price")))
        offer = c5.text_input("Our offer", value=text(existing.get("offer_price")))
        arv = c6.text_input("ARV", value=text(existing.get("arv")))
        repairs = st.text_input("Estimated repairs", value=text(existing.get("estimated_repairs")))
        notes = st.text_area("Deal notes", value=text(existing.get("notes")), height=140)
        if st.form_submit_button("Save deal", type="primary"):
            return {**existing, "title": title, "status": status, "stage": stage, "assigned_to": owner, "asking_price": asking, "offer_price": offer, "arv": arv, "estimated_repairs": repairs, "notes": notes}
    return None


require_password()
if st.sidebar.button("Log out", key="commandcore_crm_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore CRM")
st.caption("The daily workspace for sellers, properties, and deals. Records save directly into the CommandCore CRM backbone.")

entity = st.segmented_control("Workspace", options=list(ENTITY_LABELS), format_func=lambda item: ENTITY_LABELS[item], default="deals")
entity = entity or "deals"
records = load_records(entity)

search = st.text_input("Search", placeholder=f"Search {ENTITY_LABELS[entity].lower()}...").strip().lower()
if search:
    records = [record for record in records if search in " ".join(text(value).lower() for value in record.values())]

left, right = st.columns([0.38, 0.62], gap="large")
with left:
    st.subheader(ENTITY_LABELS[entity])
    st.caption(f"{len(records)} active record(s)")
    options = {record_label(entity, record): record for record in records}
    selected_label = st.radio("Open record", ["+ Create new", *options.keys()], label_visibility="collapsed")
    selected = {} if selected_label == "+ Create new" else options[selected_label]

with right:
    st.subheader("Create record" if not selected else record_label(entity, selected))
    if selected:
        meta = [text(selected.get("source")), text(selected.get("external_id"))]
        st.caption(" • ".join(item for item in meta if item))
    if entity == "contacts":
        saved = contact_form(selected)
    elif entity == "properties":
        saved = property_form(selected)
    else:
        saved = deal_form(selected)
    if saved is not None:
        result = save_record(entity, saved)
        if result.get("ok"):
            st.success("Saved to CommandCore CRM.")
            st.cache_data.clear()
            st.rerun()
        st.error(text(result.get("error")) or "CommandCore could not save this record.")

st.divider()
st.caption("This workspace manages internal CRM records only. It does not send messages, move money, sign contracts, approve offers, or perform external actions.")
