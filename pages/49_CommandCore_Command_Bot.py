from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Command Bot", page_icon="🤖", layout="wide")

SUPPORTED_INTENTS = {
    "deal_analysis": "Analyze deal",
    "prepare_offer": "Prepare offer",
    "prepare_contract": "Prepare contract",
    "title_closing": "Title / closing",
    "marketing_dispo": "Marketing / dispo",
}


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


def upsert(entity: str, record: dict[str, Any]) -> dict[str, Any]:
    result = call_crm({"action": "upsert", "entity": entity, "record": record})
    saved = result.get("record", {})
    return saved if isinstance(saved, dict) else {}


def text(value: Any) -> str:
    return str(value or "").strip()


def links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def parse_intent(command: str) -> str | None:
    value = command.lower()
    if any(term in value for term in ("contract", "cfd", "contract for deed", "purchase agreement")):
        return "prepare_contract"
    if any(term in value for term in ("offer", "make an offer", "offer draft")):
        return "prepare_offer"
    if any(term in value for term in ("analyze", "analysis", "underwrite", "comp", "comps")):
        return "deal_analysis"
    if any(term in value for term in ("title", "closing", "close this deal")):
        return "title_closing"
    if any(term in value for term in ("market", "marketing", "dispo", "disposition", "sell this")):
        return "marketing_dispo"
    return None


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


def normalized_command(command: str) -> str:
    return " ".join(command.strip().lower().split())


def command_request_external_id(deal_id: str, work_type: str, command: str) -> str:
    normalized = normalized_command(command)
    digest = hashlib.sha256(f"{deal_id}|{work_type}|{normalized}".encode()).hexdigest()[:24]
    return f"command-bot-{deal_id}-{work_type}-{digest}"


def create_lifecycle_request(
    deal: dict[str, Any],
    work_type: str,
    command: str,
) -> tuple[dict[str, Any], bool]:
    deal_id = text(deal.get("id"))
    if not deal_id:
        raise RuntimeError("Selected deal does not have an ID.")

    request_external_id = command_request_external_id(deal_id, work_type, command)
    for existing in list_records("tasks"):
        if text(existing.get("external_id")) == request_external_id:
            return existing, False

    timestamp = datetime.now(UTC).isoformat()
    label = SUPPORTED_INTENTS[work_type]
    task = upsert(
        "tasks",
        {
            "external_id": request_external_id,
            "task_type": "deal_lifecycle_request",
            "work_type": work_type,
            "title": f"{label}: {text(deal.get('title') or deal.get('name')) or deal_id}",
            "status": "open",
            "priority": "high" if work_type in {"prepare_offer", "prepare_contract", "title_closing"} else "medium",
            "source": "commandcore-command-bot",
            "command_text": command,
            "normalized_command": normalized_command(command),
            "requested_at": timestamp,
            "coordination_status": "pending",
            "external_action_started": False,
            "approval_bypassed": False,
            "links": {"deal_id": deal_id},
        },
    )
    upsert(
        "activities",
        {
            "external_id": f"{request_external_id}-activity",
            "source": "commandcore-command-bot",
            "activity_type": "command_bot_request_created",
            "title": "Command Bot created internal deal work",
            "summary": f"{label} request created from a plain-English command.",
            "occurred_at": timestamp,
            "details": {
                "command_text": command,
                "normalized_command": normalized_command(command),
                "work_type": work_type,
                "request_external_id": request_external_id,
                "external_action_started": False,
                "approval_bypassed": False,
            },
            "links": {"deal_id": deal_id, "task_id": text(task.get("id")) or None},
        },
    )
    return task, True


require_password()
if st.sidebar.button("Log out", key="command_bot_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("Command Bot")
st.caption(
    "Give CommandCore a plain-English instruction. This version can create safe internal deal work only; "
    "it cannot send, sign, approve, move money, or start an outside transaction."
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

intent = parse_intent(command) if command else None
matched = match_deals(command, active_deals, properties_by_id) if command else []
selected_deal: dict[str, Any] | None = matched[0] if len(matched) == 1 else None

if command:
    if intent:
        st.caption(f"Understood action: {SUPPORTED_INTENTS[intent]}")
    else:
        st.warning("I can currently understand deal analysis, offer prep, contract/CFD prep, title/closing, and marketing/dispo requests.")

    if len(matched) == 1:
        st.success(f"Matched deal: {deal_label(matched[0], properties_by_id)}")
    elif len(matched) > 1:
        st.warning("More than one deal matched. Choose the correct deal before creating work.")
    else:
        st.info("I could not confidently match a deal from the command. Choose the deal below.")

if active_deals and selected_deal is None:
    options = {deal_label(deal, properties_by_id): deal for deal in active_deals}
    chosen = st.selectbox("Deal", ["Select deal"] + list(options))
    if chosen != "Select deal":
        selected_deal = options[chosen]
elif not active_deals:
    st.info("There are no active CommandCore deals yet.")

can_create = bool(command and intent and selected_deal)
if st.button("Create internal work", type="primary", disabled=not can_create):
    try:
        task, created = create_lifecycle_request(selected_deal or {}, intent or "", command)
    except RuntimeError as exc:
        st.error(f"Command Bot could not create the request: {exc}")
    else:
        if created:
            st.success(
                "Internal CommandCore work was created. The lifecycle coordinator will route it through readiness, "
                "specialist prep, and required approvals. Nothing external was started."
            )
        else:
            st.info(
                "That same Command Bot request already exists for this deal. CommandCore reused the existing internal work "
                "instead of creating a duplicate."
            )
        if text(task.get("id")):
            st.caption(f"Task ID: {text(task.get('id'))}")

st.divider()
st.caption(
    "Supported now: analyze a deal, prepare an offer draft, prepare contract/CFD facts, prepare title/closing work, "
    "and prepare a marketing/dispo handoff. Consequential approvals stay with the Owner Approval Queue."
)
