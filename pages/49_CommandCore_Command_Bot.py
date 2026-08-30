from __future__ import annotations

from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.command_agent import SUPPORTED_INTENTS, dispatch_command, is_dev_command, parse_ops_intent
from supabase import create_client

st.set_page_config(page_title="CommandCore Command Bot", page_icon="🤖", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Command Bot")
    with st.form("command_bot_login"):
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


def links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def property_label(prop: dict[str, Any]) -> str:
    return text(prop.get("address") or prop.get("property_address") or prop.get("name") or prop.get("id"))


def deal_label(deal: dict[str, Any], properties_by_id: dict[str, dict[str, Any]]) -> str:
    prop_id = text(links(deal).get("property_id") or deal.get("property_id"))
    prop = properties_by_id.get(prop_id, {})
    return text(deal.get("title") or deal.get("name")) or property_label(prop) or text(deal.get("id"))


def match_deals(
    command: str,
    deals: list[dict[str, Any]],
    properties_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    value = command.lower()
    matches: list[dict[str, Any]] = []
    for deal in deals:
        prop_id = text(links(deal).get("property_id") or deal.get("property_id"))
        prop = properties_by_id.get(prop_id, {})
        candidates = {
            text(deal.get("title")),
            text(deal.get("name")),
            text(deal.get("id")),
            property_label(prop),
        }
        searchable = [candidate.lower() for candidate in candidates if len(candidate) >= 4]
        if any(candidate in value for candidate in searchable):
            matches.append(deal)
    return matches


require_password()
if st.sidebar.button("Log out", key="command_bot_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("Command Bot")
st.caption(
    "Give CommandCore a plain-English operations instruction. Command Agent routes one simulated Task Agent only; "
    "nothing is written, sent, signed, approved, spent, or moved."
)

try:
    deals = list_records("deals")
    properties = list_records("properties")
except RuntimeError as exc:
    st.error(f"Command Bot data could not be loaded: {exc}")
    st.stop()

properties_by_id = {text(prop.get("id")): prop for prop in properties if text(prop.get("id"))}
active_deals = [
    deal
    for deal in deals
    if text(deal.get("status")).lower()
    not in {"closed", "sold", "dead", "lost", "cancelled", "canceled", "archived"}
]

command = st.text_input(
    "What do you need?",
    placeholder="Example: Prepare the CFD for 123 Main Street",
)

dev_command = is_dev_command(command) if command else False
intent = parse_ops_intent(command) if command and not dev_command else None
matched = match_deals(command, active_deals, properties_by_id) if command and not dev_command else []
selected_deal: dict[str, Any] | None = matched[0] if len(matched) == 1 else None

if command:
    if dev_command:
        st.warning("That belongs to the Dev team.")
    elif intent:
        st.caption(f"Understood action: {SUPPORTED_INTENTS[intent]}")
    else:
        st.warning(
            "Tell me whether you want deal analysis, offer prep, contract/CFD prep, title/closing, "
            "or marketing/dispo work."
        )

    if not dev_command:
        if len(matched) == 1:
            st.success(f"Matched deal: {deal_label(matched[0], properties_by_id)}")
        elif len(matched) > 1:
            st.warning("More than one deal matched. Choose the correct deal before creating work.")
        else:
            st.info("I could not confidently match a deal from the command. Choose the deal below.")

if active_deals and selected_deal is None and not dev_command:
    options = {deal_label(deal, properties_by_id): deal for deal in active_deals}
    chosen = st.selectbox("Deal", ["Select deal"] + list(options))
    if chosen != "Select deal":
        selected_deal = options[chosen]
elif not active_deals:
    st.info("There are no active CommandCore deals yet.")

can_run = bool(command and intent and selected_deal and not dev_command)
if st.button("Simulate internal work", type="primary", disabled=not can_run):
    result = dispatch_command(command=command, deal=selected_deal)
    if result.status == "simulated" and len(result.task_agent_runs) == 1:
        run = result.task_agent_runs[0]
        st.success("One Task Agent simulated the internal work. Nothing external or production-facing started.")
        st.caption(f"Run ID: {run.run_id}")
        st.caption("CRM intent: blocked by simulation mode")
    elif result.needs_you:
        st.warning(result.needs_you)
    else:
        st.error("The simulated Task Agent run did not complete safely.")

st.divider()
st.caption(
    "Ops only: analyze a deal, prepare an offer draft, prepare contract/CFD facts, prepare title/closing work, "
    "or prepare a marketing/dispo handoff. Software changes belong to the separate Dev team and cannot start here."
)
