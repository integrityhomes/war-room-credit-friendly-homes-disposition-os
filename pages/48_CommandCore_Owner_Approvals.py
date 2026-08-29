from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_contract_controls import legal_template_blocker, pending_document
from supabase import create_client

st.set_page_config(page_title="CommandCore Owner Approvals", page_icon="✅", layout="wide")

OWNER_NAMES = {"Shawn", "Sabrina"}


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Owner Approvals")
    with st.form("owner_approval_login"):
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


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def pending_offer(record: dict[str, Any]) -> bool:
    return text(record.get("status")).lower() == "draft_pending_owner_approval"


def verify_owner_pin(supplied: str) -> bool:
    expected = str(st.secrets.get("OWNER_APPROVAL_PIN", "")).strip()
    return bool(expected and supplied and supplied == expected)


def save_decision(
    *,
    entity: str,
    record: dict[str, Any],
    decision: str,
    owner_name: str,
    reason: str,
) -> None:
    record_id = text(record.get("id"))
    if not record_id:
        raise RuntimeError("Approval item has no record ID.")
    timestamp = now_iso()
    new_status = "owner_approved" if decision == "approve" else "owner_rejected"
    deal_id = text(links(record).get("deal_id") or record.get("deal_id"))
    history_external_id = f"owner-decision-{entity}-{record_id}"

    # Write deterministic permanent history first. If the record-state write fails,
    # a retry updates this same activity instead of creating a duplicate or losing history.
    upsert(
        "activities",
        {
            "source": "commandcore-owner-approval-queue",
            "external_id": history_external_id,
            "activity_type": "owner_approval_decision",
            "title": f"Owner {decision}d {entity[:-1] if entity.endswith('s') else entity}",
            "summary": f"{owner_name} {decision}d an owner-gated CommandCore item.",
            "occurred_at": timestamp,
            "details": {
                "entity": entity,
                "record_id": record_id,
                "decision": decision,
                "owner_name": owner_name,
                "reason": reason or None,
                "owner_decision_recorded": True,
                "external_action_started": False,
            },
            "links": {"deal_id": deal_id or None, f"{entity[:-1]}_id": record_id},
        },
    )

    updated = {
        **record,
        "status": new_status,
        "owner_approval_status": new_status,
        "owner_approval_decision": decision,
        "owner_approved_by": owner_name if decision == "approve" else None,
        "owner_rejected_by": owner_name if decision == "reject" else None,
        "owner_decided_at": timestamp,
        "owner_decision_reason": reason or None,
        "owner_decision_history_external_id": history_external_id,
        "owner_decision_history_recorded": True,
        "external_action_started": False,
    }
    upsert(entity, updated)


def render_item(entity: str, record: dict[str, Any], deals_by_id: dict[str, dict[str, Any]]) -> None:
    record_id = text(record.get("id"))
    deal_id = text(links(record).get("deal_id") or record.get("deal_id"))
    deal = deals_by_id.get(deal_id, {})
    title = text(deal.get("title")) or text(record.get("name")) or f"{entity.title()} approval"
    amount = record.get("amount")
    status = text(record.get("status"))

    with st.container(border=True):
        st.markdown(f"#### {title}")
        c1, c2, c3 = st.columns(3)
        c1.caption(f"Type: {entity[:-1] if entity.endswith('s') else entity}")
        c2.caption(f"Status: {status}")
        c3.caption(f"Deal ID: {deal_id or 'Not linked'}")
        if amount not in (None, ""):
            st.metric("Draft amount", f"${float(amount):,.0f}")

        if entity == "offers":
            st.warning("Approving this records owner approval only. It does not send the offer or bind the company.")
            terms = record.get("terms")
            if isinstance(terms, dict):
                facts = terms.get("facts")
                if isinstance(facts, dict):
                    st.json(facts, expanded=False)
        else:
            st.info("This approval records your decision only. It does not sign, send, or externally execute anything.")
            facts = record.get("facts")
            if isinstance(facts, dict):
                st.json(facts, expanded=False)
            template_reference = record.get("approved_template_reference")
            if isinstance(template_reference, dict):
                st.caption("Approved legal template reference")
                st.json(template_reference, expanded=False)

        owner_name = st.selectbox(
            "Decision maker",
            ["Select owner", "Shawn", "Sabrina"],
            key=f"owner-{entity}-{record_id}",
        )
        reason = st.text_input(
            "Decision note (optional)",
            key=f"reason-{entity}-{record_id}",
            placeholder="Example: Approved offer amount; proceed to the next internal step.",
        )
        pin = st.text_input(
            "Owner approval PIN",
            type="password",
            key=f"pin-{entity}-{record_id}",
            help="This separate PIN prevents ordinary app users from approving owner-gated actions.",
        )
        confirm = st.checkbox(
            "I understand this records an owner decision and I am the owner named above.",
            key=f"confirm-{entity}-{record_id}",
        )

        approve_col, reject_col = st.columns(2)
        if approve_col.button("Approve", type="primary", key=f"approve-{entity}-{record_id}", use_container_width=True):
            if owner_name not in OWNER_NAMES:
                st.error("Choose Shawn or Sabrina as the decision maker.")
            elif not confirm:
                st.error("Confirm the owner decision before approving.")
            elif not verify_owner_pin(pin):
                st.error("Owner approval PIN is missing or incorrect.")
            else:
                save_decision(
                    entity=entity,
                    record=record,
                    decision="approve",
                    owner_name=owner_name,
                    reason=reason,
                )
                st.success("Owner approval recorded. No external action was started.")
                st.rerun()

        if reject_col.button("Reject", key=f"reject-{entity}-{record_id}", use_container_width=True):
            if owner_name not in OWNER_NAMES:
                st.error("Choose Shawn or Sabrina as the decision maker.")
            elif not confirm:
                st.error("Confirm the owner decision before rejecting.")
            elif not verify_owner_pin(pin):
                st.error("Owner approval PIN is missing or incorrect.")
            else:
                save_decision(
                    entity=entity,
                    record=record,
                    decision="reject",
                    owner_name=owner_name,
                    reason=reason,
                )
                st.success("Owner rejection recorded. No external action was started.")
                st.rerun()


def render_legal_template_blocker(record: dict[str, Any], deals_by_id: dict[str, dict[str, Any]]) -> None:
    deal_id = text(links(record).get("deal_id") or record.get("deal_id"))
    deal = deals_by_id.get(deal_id, {})
    title = text(deal.get("title")) or text(record.get("name")) or "Contract preparation"
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.error("Blocked: an approved legal contract template is required before this can become an owner-approval item.")
        st.caption(f"Deal ID: {deal_id or 'Not linked'}")
        facts = record.get("facts")
        if isinstance(facts, dict):
            st.json(facts, expanded=False)
        st.caption("This item cannot be approved here. No legal terms will be generated, changed, signed, or sent automatically.")


require_password()
if st.sidebar.button("Log out", key="owner_approval_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("Owner Approval Queue")
st.caption("One place for Shawn and Sabrina to review consequential CommandCore decisions before anything external happens.")

if not str(st.secrets.get("OWNER_APPROVAL_PIN", "")).strip():
    st.warning(
        "Owner decisions are locked because OWNER_APPROVAL_PIN is not configured in Streamlit Secrets. "
        "The queue can be reviewed safely, but approvals and rejections cannot be recorded yet."
    )

try:
    offers = [record for record in list_records("offers") if pending_offer(record)]
    all_documents = list_records("documents")
    documents = [record for record in all_documents if pending_document(record)]
    legal_blockers = [record for record in all_documents if legal_template_blocker(record)]
    deals = list_records("deals")
except RuntimeError as exc:
    st.error(f"Owner approval data could not be loaded: {exc}")
    st.stop()

deals_by_id = {text(record.get("id")): record for record in deals if text(record.get("id"))}

m1, m2, m3, m4 = st.columns(4)
m1.metric("Pending approvals", len(offers) + len(documents))
m2.metric("Offer decisions", len(offers))
m3.metric("Document / closing decisions", len(documents))
m4.metric("Legal template blockers", len(legal_blockers))

if legal_blockers:
    st.subheader("Blocked contract preparation")
    for item in legal_blockers:
        render_legal_template_blocker(item, deals_by_id)

if not offers and not documents:
    st.success("No owner-gated approvals are waiting right now.")
else:
    if offers:
        st.subheader("Offers")
        for item in offers:
            render_item("offers", item, deals_by_id)

    if documents:
        st.subheader("Contracts, title & closing")
        for item in documents:
            render_item("documents", item, deals_by_id)

st.divider()
st.caption(
    "Approval in this queue never sends a message, signs a contract, changes legal terms, moves money, changes bank data, "
    "or starts an external transaction. Those actions require their own controlled next step."
)
