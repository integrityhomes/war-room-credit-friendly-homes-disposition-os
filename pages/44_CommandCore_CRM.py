from __future__ import annotations

from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_agent_finder_ui import render_agent_finder
from supabase import create_client

st.set_page_config(page_title="CommandCore CRM", page_icon="🏠", layout="wide")

ENTITY_LABELS = {"contacts": "Contacts", "properties": "Properties", "deals": "Deals"}
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


def links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def load_records(entity: str) -> list[dict[str, Any]]:
    result = call_crm({"action": "list", "entity": entity, "limit": 500})
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def save_record(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    return call_crm({"action": "upsert", "entity": entity, "record": record})


def saved_record(result: dict[str, Any]) -> dict[str, Any]:
    record = result.get("record")
    return record if isinstance(record, dict) else {}


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


def select_option(label: str, options: list[str], current: str, *, key: str | None = None) -> str:
    values = list(options)
    if current and current not in values:
        values.insert(0, current)
    index = values.index(current) if current in values else 0
    return st.selectbox(label, values, index=index, key=key)


def create_guided_lead(
    seller: dict[str, Any],
    property_record: dict[str, Any],
    deal: dict[str, Any],
) -> tuple[bool, str, str]:
    contact_result = save_record("contacts", seller)
    if not contact_result.get("ok"):
        return False, text(contact_result.get("error")) or "Seller information could not be saved.", ""
    contact_id = text(saved_record(contact_result).get("id"))
    if not contact_id:
        return False, "Seller information saved, but CommandCore did not return the seller record ID.", ""

    property_result = save_record("properties", property_record)
    if not property_result.get("ok"):
        return False, text(property_result.get("error")) or "Property information could not be saved.", ""
    property_id = text(saved_record(property_result).get("id"))
    if not property_id:
        return False, "Property information saved, but CommandCore did not return the property record ID.", ""

    deal_result = save_record(
        "deals",
        {
            **deal,
            "links": {"contact_id": contact_id, "property_id": property_id},
        },
    )
    if not deal_result.get("ok"):
        return False, text(deal_result.get("error")) or "The deal could not be created.", ""
    deal_id = text(saved_record(deal_result).get("id"))
    if not deal_id:
        return False, "The deal was saved, but CommandCore did not return the deal ID.", ""
    return True, "Lead created and linked successfully.", deal_id


def guided_lead_intake() -> None:
    st.subheader("Add New Lead")
    st.caption(
        "Enter the seller and property once. CommandCore creates and links the seller, property, and deal automatically."
    )

    with st.form("commandcore_guided_lead_intake"):
        st.markdown("### 1. Seller")
        seller_left, seller_right = st.columns(2)
        first = seller_left.text_input("First name")
        last = seller_right.text_input("Last name")
        phone = seller_left.text_input("Phone")
        email = seller_right.text_input("Email")

        st.markdown("### 2. Property")
        address = st.text_input("Property address")
        city_col, state_col, zip_col = st.columns(3)
        city = city_col.text_input("City")
        state = state_col.text_input("State")
        zip_code = zip_col.text_input("ZIP")

        st.markdown("### 3. Deal")
        deal_left, deal_middle, deal_right = st.columns(3)
        asking = deal_left.text_input("Seller asking price")
        owner = deal_middle.text_input("Assigned to")
        source = deal_right.text_input("Lead source", placeholder="Texting, MLS, referral, Facebook...")
        notes = st.text_area("What should the team know?", height=110)

        with st.expander("More deal details (optional)"):
            detail_left, detail_middle, detail_right = st.columns(3)
            stage = detail_left.selectbox("Pipeline stage", PIPELINE_STAGES, index=0)
            status = detail_middle.selectbox("Status", DEAL_STATUSES, index=0)
            arv = detail_right.text_input("ARV")
            repair_left, offer_right = st.columns(2)
            repairs = repair_left.text_input("Estimated repairs")
            offer = offer_right.text_input("Our offer")

        submitted = st.form_submit_button("Create Lead & Open Deal", type="primary", use_container_width=True)

    if not submitted:
        return
    if not address.strip():
        st.error("Property address is required before CommandCore can create the deal.")
        return
    if not (first.strip() or last.strip() or phone.strip() or email.strip()):
        st.error("Add at least the seller's name, phone, or email.")
        return

    seller_name = f"{first} {last}".strip()
    title = " — ".join(value for value in [address.strip(), seller_name] if value)
    ok, message, deal_id = create_guided_lead(
        {
            "first_name": first.strip(),
            "last_name": last.strip(),
            "name": seller_name,
            "phone": phone.strip(),
            "email": email.strip(),
            "source": source.strip() or "commandcore-lead-intake",
        },
        {
            "address": address.strip(),
            "city": city.strip(),
            "state": state.strip(),
            "zip": zip_code.strip(),
            "source": source.strip() or "commandcore-lead-intake",
        },
        {
            "title": title or address.strip(),
            "status": status,
            "stage": stage,
            "assigned_to": owner.strip(),
            "asking_price": asking.strip(),
            "offer_price": offer.strip(),
            "arv": arv.strip(),
            "estimated_repairs": repairs.strip(),
            "notes": notes.strip(),
            "lead_source": source.strip(),
            "source": "commandcore-lead-intake",
        },
    )
    if not ok:
        st.error(message)
        return
    st.session_state["commandcore_selected_deal_id"] = deal_id
    st.success(message)
    st.switch_page("pages/45_CommandCore_Deal_Record.py")


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
            return {
                **existing,
                "first_name": first,
                "last_name": last,
                "name": f"{first} {last}".strip(),
                "phone": phone,
                "email": email,
                "company": company,
                "notes": notes,
            }
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
            return {
                **existing,
                "address": address,
                "city": city,
                "state": state,
                "zip": zip_code,
                "bedrooms": beds,
                "bathrooms": baths,
                "square_feet": sqft,
                "parcel_id": parcel,
                "notes": notes,
            }
    return None


def deal_form(
    existing: dict[str, Any],
    contacts: list[dict[str, Any]],
    properties: list[dict[str, Any]],
) -> dict[str, Any] | None:
    existing_links = links(existing)
    contact_options = {text(row.get("id")): record_label("contacts", row) for row in contacts if text(row.get("id"))}
    property_options = {
        text(row.get("id")): record_label("properties", row)
        for row in properties
        if text(row.get("id"))
    }
    current_contact_id = text(existing_links.get("contact_id"))
    current_property_id = text(existing_links.get("property_id"))

    with st.form("crm_deal_form"):
        title = st.text_input("Deal name", value=text(existing.get("title")))
        st.caption("The seller and property linked here appear together in the Unified Deal Record.")
        link_left, link_right = st.columns(2)
        contact_ids = ["", *contact_options]
        property_ids = ["", *property_options]
        contact_index = contact_ids.index(current_contact_id) if current_contact_id in contact_ids else 0
        property_index = property_ids.index(current_property_id) if current_property_id in property_ids else 0
        contact_id = link_left.selectbox(
            "Seller / contact",
            contact_ids,
            index=contact_index,
            format_func=lambda value: "Not linked" if not value else contact_options.get(value, value),
        )
        property_id = link_right.selectbox(
            "Property",
            property_ids,
            index=property_index,
            format_func=lambda value: "Not linked" if not value else property_options.get(value, value),
        )
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox(
            "Status",
            [*DEAL_STATUSES, *([text(existing.get("status"))] if text(existing.get("status")) not in DEAL_STATUSES else [])],
            index=0 if not text(existing.get("status")) else ([*DEAL_STATUSES, text(existing.get("status"))].index(text(existing.get("status"))) if text(existing.get("status")) not in DEAL_STATUSES else DEAL_STATUSES.index(text(existing.get("status")))),
        )
        stage_values = [*PIPELINE_STAGES]
        current_stage = text(existing.get("stage"))
        if current_stage and current_stage not in stage_values:
            stage_values.append(current_stage)
        stage = c2.selectbox("Pipeline stage", stage_values, index=stage_values.index(current_stage) if current_stage in stage_values else 0)
        owner = c3.text_input("Assigned to", value=text(existing.get("assigned_to")))
        c4, c5, c6 = st.columns(3)
        asking = c4.text_input("Asking price", value=text(existing.get("asking_price")))
        offer = c5.text_input("Our offer", value=text(existing.get("offer_price")))
        arv = c6.text_input("ARV", value=text(existing.get("arv")))
        repairs = st.text_input("Estimated repairs", value=text(existing.get("estimated_repairs")))
        notes = st.text_area("Deal notes", value=text(existing.get("notes")), height=140)
        if st.form_submit_button("Save deal", type="primary"):
            updated_links = {**existing_links}
            if contact_id:
                updated_links["contact_id"] = contact_id
            else:
                updated_links.pop("contact_id", None)
            if property_id:
                updated_links["property_id"] = property_id
            else:
                updated_links.pop("property_id", None)
            return {
                **existing,
                "title": title,
                "status": status,
                "stage": stage,
                "assigned_to": owner,
                "asking_price": asking,
                "offer_price": offer,
                "arv": arv,
                "estimated_repairs": repairs,
                "notes": notes,
                "links": updated_links,
            }
    return None


def manage_records() -> None:
    st.subheader("Find & Edit Records")
    st.caption("Use this area when you need to correct an existing seller, property, or deal.")
    entity = st.segmented_control(
        "Record type",
        options=list(ENTITY_LABELS),
        format_func=lambda item: ENTITY_LABELS[item],
        default="deals",
    )
    entity = entity or "deals"
    records = load_records(entity)

    search = st.text_input("Search", placeholder=f"Search {ENTITY_LABELS[entity].lower()}...").strip().lower()
    if search:
        records = [
            record
            for record in records
            if search in " ".join(text(value).lower() for value in record.values())
        ]

    left, right = st.columns([0.38, 0.62], gap="large")
    with left:
        st.markdown(f"### {ENTITY_LABELS[entity]}")
        st.caption(f"{len(records)} active record(s)")
        options = {record_label(entity, record): record for record in records}
        selected_label = st.radio(
            "Open record",
            ["+ Create standalone record", *options.keys()],
            label_visibility="collapsed",
        )
        selected = {} if selected_label == "+ Create standalone record" else options[selected_label]

    with right:
        st.markdown("### Create standalone record" if not selected else f"### {record_label(entity, selected)}")
        if selected:
            meta = [text(selected.get("source")), text(selected.get("external_id"))]
            if any(meta):
                st.caption(" • ".join(item for item in meta if item))
        if entity == "deals" and selected and text(selected.get("id")):
            if st.button("Open Unified Deal Record", type="primary", use_container_width=True):
                st.session_state["commandcore_selected_deal_id"] = text(selected.get("id"))
                st.switch_page("pages/45_CommandCore_Deal_Record.py")
        if entity == "contacts":
            if selected and text(selected.get("id")):
                render_agent_finder(
                    contact=selected,
                    deals=load_records("deals"),
                    properties=load_records("properties"),
                    save_record=save_record,
                    secrets=st.secrets,
                )
            saved = contact_form(selected)
        elif entity == "properties":
            saved = property_form(selected)
        else:
            saved = deal_form(selected, load_records("contacts"), load_records("properties"))
        if saved is not None:
            result = save_record(entity, saved)
            if result.get("ok"):
                st.success("Saved to CommandCore CRM.")
                st.rerun()
            st.error(text(result.get("error")) or "CommandCore could not save this record.")


require_password()
if st.sidebar.button("Log out", key="commandcore_crm_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("Leads & CRM")
st.caption("Add a new lead in one simple flow, or find an existing seller, property, or deal when you need it.")

new_lead_tab, manage_tab = st.tabs(["Add New Lead", "Find & Edit"])
with new_lead_tab:
    guided_lead_intake()
with manage_tab:
    manage_records()

st.divider()
st.caption(
    "CommandCore saves internal CRM records here. Creating a lead does not send messages, make an offer, sign a contract, "
    "approve terms, or move money."
)
