from __future__ import annotations

import json
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_ux import advanced_settings, render_page_header, show_error
from cfh_disposition.corepilot_orchestrator import CorePilotResult, run_corepilot
from cfh_disposition.corepilot_sources import validated_crm_entities
from cfh_disposition.corepilot_tools import CorePilotActionClass
from supabase import create_client

st.set_page_config(page_title="CorePilot", page_icon="🤖", layout="wide")

QUICK_ACTIONS = ("What needs my attention?", "Find a deal", "Show my work", "Review communications")


def render_mobile_styles() -> None:
    """Keep the one CorePilot experience usable on laptop and phone screens."""
    st.markdown(
        """
        <style>
        html, body, [data-testid="stAppViewContainer"] { max-width: 100%; overflow-x: hidden; }
        [data-testid="stMainBlockContainer"] { padding-top: 1.5rem; }
        .stButton > button, .stFormSubmitButton > button {
            min-height: 44px;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .stTextInput input { min-height: 44px; font-size: 16px; }
        @media (max-width: 640px) {
            [data-testid="stMainBlockContainer"] { padding: 1rem 0.75rem 2rem; }
            [data-testid="stHorizontalBlock"] { flex-direction: column; gap: 0.5rem; }
            [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; }
            h1 { font-size: 1.8rem !important; }
            h2 { font-size: 1.35rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until the app password is configured.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CorePilot")
    with st.form("corepilot_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("That password did not match. Try again.")
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
    response = get_supabase().functions.invoke("commandcore-crm-core", {"body": {"action": "list", "entity": entity, "limit": 500}})
    records = response_dictionary(response).get("records", [])
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def load_corepilot_records() -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    records: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for entity in validated_crm_entities():
        try:
            records[entity] = list_records(entity)
        except Exception as exc:  # UI safety boundary: never expose provider tracebacks.
            records[entity] = []
            errors[entity] = type(exc).__name__
    return records, errors


def render_result(result: CorePilotResult) -> None:
    if result.clarification:
        st.info(result.clarification)
    st.markdown("### What I found")
    for item in result.what_i_found:
        st.write(f"• {item}")
    if not result.what_i_found:
        st.caption("No verified result yet.")
    st.markdown("### Needs attention")
    for item in result.needs_attention:
        st.warning(item)
    if not result.needs_attention:
        st.caption("Nothing additional was flagged from the records reviewed.")
    st.markdown("### Recommended next step")
    st.info(result.recommended_next_step)
    with advanced_settings():
        st.caption("CorePilot safety summary")
        st.write(f"Action class: {result.action_class.value}")
        st.write(f"Records changed: {result.records_written}")
        st.write(f"External actions started: {result.external_actions_started}")
        if result.capability_names:
            st.write("Capabilities used: " + ", ".join(result.capability_names))


render_mobile_styles()
require_password()
if st.sidebar.button("Log out", key="corepilot_logout"):
    st.session_state.authenticated = False
    st.rerun()

render_page_header("CorePilot", "Ask CorePilot to find information, explain what needs attention, or prepare the next step.")
st.markdown("## What do you need?")
columns = st.columns(4)
for index, label in enumerate(QUICK_ACTIONS):
    if columns[index].button(label, key=f"corepilot_quick_{index}", use_container_width=True):
        st.session_state["corepilot_request"] = label

with st.form("corepilot_request_form"):
    request = st.text_input("Ask CorePilot", key="corepilot_request", placeholder="Example: What is holding this closing up?")
    submitted = st.form_submit_button("Ask CorePilot", type="primary")

if submitted:
    try:
        records, source_errors = load_corepilot_records()
    except (RuntimeError, ValueError):
        show_error("CorePilot could not safely read CommandCore records.", next_step="Check the app connection and try again.")
    else:
        result = run_corepilot(request, records, current_deal_id=str(st.session_state.get("commandcore_selected_deal_id", "")), current_user=str(st.session_state.get("commandcore_worker_name", "")))
        render_result(result)
        if source_errors:
            st.warning("CorePilot couldn't check one part of CommandCore right now. Nothing was changed.")
            with advanced_settings():
                st.caption("Unavailable read sources")
                for source, error_type in source_errors.items():
                    st.write(f"{source}: {error_type}")
        if result.action_class is CorePilotActionClass.APPROVAL_REQUIRED:
            st.caption("CorePilot stopped before the protected action. No approval was granted and nothing was executed.")

st.caption("CorePilot reads existing CommandCore records and can create private preparation previews. It cannot send, sign, approve, publish, spend, or change records.")
