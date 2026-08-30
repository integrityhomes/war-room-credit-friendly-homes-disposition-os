from __future__ import annotations

from typing import Any

import streamlit as st
from supabase import create_client

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_contract_template_ui import render_contract_template_library


st.set_page_config(page_title="CommandCore Contract Templates", page_icon="📄", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("CommandCore is locked until APP_PASSWORD is configured.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore")
    with st.form("commandcore_template_login"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_supabase() -> Any:
    url = str(st.secrets.get("SUPABASE_URL", "")).strip()
    key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not url or not key:
        raise RuntimeError("CommandCore storage is not configured.")
    return create_client(url, key)


def call_crm(payload: dict[str, Any]) -> dict[str, Any]:
    response = get_supabase().functions.invoke("commandcore-crm-core", {"body": payload})
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    return data if isinstance(data, dict) else {}


def text(value: Any) -> str:
    return str(value or "").strip()


def deal_label(deal: dict[str, Any]) -> str:
    return text(deal.get("title")) or text(deal.get("stage")) or text(deal.get("id"))


require_password()
if st.sidebar.button("Log out", key="commandcore_template_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("Contract Templates")
st.caption(
    "Keep contract packages current without overwriting an approved legal version. "
    "New versions stay pending until the required approval is recorded."
)

try:
    result = call_crm({"action": "list", "entity": "deals", "limit": 500})
    deals = result.get("records", [])
    deals = deals if isinstance(deals, list) else []
except Exception:
    st.error("CommandCore could not load Deals right now.")
    st.stop()

if not deals:
    st.info("Add a Deal first so CommandCore can use its contract package and property state as defaults.")
    st.page_link("pages/44_CommandCore_CRM.py", label="Go to Leads & CRM", use_container_width=True)
    st.stop()

options = {deal_label(deal): deal for deal in deals}
labels = list(options)
requested_id = text(st.session_state.get("commandcore_selected_deal_id"))
default_index = next(
    (index for index, label in enumerate(labels) if text(options[label].get("id")) == requested_id),
    0,
)
selected_label = st.selectbox("Use Deal defaults from", labels, index=default_index)
deal = options[selected_label]
deal_id = text(deal.get("id"))
st.session_state["commandcore_selected_deal_id"] = deal_id

render_contract_template_library(
    deal=deal,
    deal_id=deal_id,
    get_supabase=get_supabase,
)
