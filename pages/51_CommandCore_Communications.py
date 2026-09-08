from __future__ import annotations

import json
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_nevaeh_inbox import (
    NevaehInboxCategory,
    NevaehInboxItem,
    build_nevaeh_inbox,
)
from cfh_disposition.commandcore_ux import render_page_header, show_error, show_warning
from supabase import create_client

st.set_page_config(page_title="CommandCore Communications", page_icon="💬", layout="wide")

VIEWS = (
    "New",
    "Needs attention",
    "Assigned to me",
    "Seller",
    "Buyer",
    "Deal-related",
    "STOP / Consent",
    "Money / Legal",
    "Unmatched",
)

VIEW_CATEGORY = {
    "New": NevaehInboxCategory.NEW,
    "Needs attention": NevaehInboxCategory.NEEDS_REVIEW,
    "Assigned to me": NevaehInboxCategory.ASSIGNED_TO_ME,
    "Seller": NevaehInboxCategory.SELLER,
    "Buyer": NevaehInboxCategory.BUYER,
    "Deal-related": NevaehInboxCategory.MATCHED_TO_DEAL,
    "STOP / Consent": NevaehInboxCategory.STOP_CONSENT,
    "Money / Legal": NevaehInboxCategory.MONEY_LEGAL,
    "Unmatched": NevaehInboxCategory.UNMATCHED,
}


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until the app password is configured.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Communications")
    st.caption("Private internal access")
    with st.form("commandcore_communications_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("That password did not work.")
    st.stop()


@st.cache_resource
def get_supabase():
    url = str(st.secrets.get("SUPABASE_URL", "")).strip()
    key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not url or not key:
        raise RuntimeError("CommandCore storage is not configured.")
    return create_client(url, key)


def response_dictionary(response: object) -> dict[str, Any]:
    value = response if isinstance(response, dict) else getattr(response, "data", None)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = json.loads(bytes(value).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
    return value if isinstance(value, dict) else {}


def list_records(entity: str) -> list[dict[str, Any]]:
    response = get_supabase().functions.invoke(
        "commandcore-crm-core",
        {"body": {"action": "list", "entity": entity, "limit": 500}},
    )
    records = response_dictionary(response).get("records", [])
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def category_count(items: tuple[NevaehInboxItem, ...], view: str) -> int:
    category = VIEW_CATEGORY[view]
    return sum(category in item.categories for item in items)


def render_item(item: NevaehInboxItem, *, expanded: bool) -> None:
    urgent = NevaehInboxCategory.STOP_CONSENT in item.categories
    protected = NevaehInboxCategory.MONEY_LEGAL in item.categories
    title = f"{item.person} · {item.channel} · {item.priority} priority"
    with st.expander(title, expanded=expanded):
        if urgent:
            show_warning(
                "This message may contain a STOP or consent request.",
                next_step="Do not contact this person until the consent status is reviewed in the protected workflow.",
            )
        if protected:
            show_warning(
                "This message concerns money or a legal matter.",
                next_step="Follow the owner-approval and legal/financial review process before taking action.",
            )
        left, right = st.columns(2)
        left.write(f"**Related property:** {item.related_property}")
        left.write(f"**Related deal:** {item.related_deal}")
        right.write(f"**Assigned team member:** {item.assigned_worker}")
        right.write(f"**What they want:** {item.classification}")
        st.write(f"**Recommended next action:** {item.recommended_next_step}")
        if item.confidence.casefold() in {"insufficient", "low"}:
            st.warning(f"Identity match confidence: {item.confidence}. Review before relying on this match.")
        with st.expander("Advanced details", expanded=False):
            st.caption(f"Communication ID: {item.communication_id}")
            st.caption(f"Received: {item.received_at}")
            st.caption(f"Match confidence: {item.confidence}")
            st.caption("Views: " + ", ".join(category.value for category in item.categories))
            st.caption("Records written: 0 · Consent changes: 0 · Provider actions: 0")


require_password()
if st.sidebar.button("Log out", key="commandcore_communications_logout"):
    st.session_state.authenticated = False
    st.rerun()

render_page_header(
    "Communications",
    "Review incoming messages, understand what needs attention, and see the safest next step.",
)
st.caption("Read-only view · Nevaeh cannot send, call, approve, change consent, or change records here.")

try:
    communications = list_records("communications")
    contacts = list_records("contacts")
    properties = list_records("properties")
    deals = list_records("deals")
except Exception:
    show_error(
        "Communications could not be loaded safely. Nothing was changed.",
        next_step="Try again. If the problem continues, ask an administrator to check CommandCore storage.",
    )
    st.stop()

assigned_workers = sorted(
    {
        str(record.get("assigned_to") or record.get("assigned_worker") or "").strip()
        for record in (*contacts, *deals)
        if str(record.get("assigned_to") or record.get("assigned_worker") or "").strip()
    }
)
viewer = st.selectbox("Viewing as", ["All team members", *assigned_workers])
assigned_to = "" if viewer == "All team members" else viewer
items = build_nevaeh_inbox(
    communications,
    contacts=contacts,
    properties=properties,
    deals=deals,
    assigned_to=assigned_to,
)

view = st.segmented_control("Show", VIEWS, default="New", selection_mode="single") or "New"
if view == "Assigned to me" and not assigned_to:
    show_warning(
        "Choose your name before using Assigned to me.",
        next_step="Select your name from Viewing as above.",
    )
    filtered: tuple[NevaehInboxItem, ...] = ()
else:
    category = VIEW_CATEGORY[view]
    filtered = tuple(item for item in items if category in item.categories)

summary = st.columns(3)
summary[0].metric("In this view", len(filtered))
summary[1].metric("Needs attention", category_count(items, "Needs attention"))
summary[2].metric("STOP / Consent", category_count(items, "STOP / Consent"))

if not filtered:
    st.info("No incoming communications match this view.")
else:
    for index, item in enumerate(filtered):
        render_item(item, expanded=index == 0)

st.caption(
    "This hub reads the existing CommandCore communications entity. It does not create an inbox, write CRM data, "
    "change consent or assignments, activate providers, or start outbound communication."
)
