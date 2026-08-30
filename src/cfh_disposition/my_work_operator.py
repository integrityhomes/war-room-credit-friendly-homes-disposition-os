from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import streamlit as st

OPERATOR_STATE_BUCKET = "commandcore-operator-state"


def _action_id(item: dict[str, Any]) -> str:
    explicit = str(item.get("action_id", "") or "").strip()
    if explicit:
        return explicit
    dispatch_id = str(item.get("dispatch_id", "") or "").strip()
    channel = str(item.get("channel_key", "") or "").strip()
    return f"{dispatch_id}_{channel}".strip("_")


def load_operator_states(client: Any) -> dict[str, dict[str, Any]]:
    try:
        rows = client.storage.from_(OPERATOR_STATE_BUCKET).list("actions") or []
    except Exception:
        return {}
    states: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(OPERATOR_STATE_BUCKET).download(f"actions/{name}")
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        action_id = str(parsed.get("action_id", "") or "").strip()
        if action_id:
            states[action_id] = parsed
    return states


def operator_state_for(item: dict[str, Any], states: dict[str, dict[str, Any]]) -> str:
    state = states.get(_action_id(item), {})
    return str(state.get("state", "unacknowledged") or "unacknowledged").strip().lower()


def evaluate_escalations(
    items: list[dict[str, Any]],
    states: dict[str, dict[str, Any]],
    call_function: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = call_function(
        "commandcore-aging-escalation",
        {"items": items, "operator_states": states},
    )
    escalations = result.get("escalations") if isinstance(result.get("escalations"), list) else []
    return {
        str(record.get("action_id", "")): record
        for record in escalations
        if isinstance(record, dict) and str(record.get("action_id", "")).strip()
    }


def render_operator_review(
    items: list[dict[str, Any]],
    *,
    client: Any,
    call_function: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> None:
    if not items:
        return
    states = load_operator_states(client)
    try:
        escalations = evaluate_escalations(items, states, call_function)
    except Exception:
        escalations = {}

    def escalation_for(item: dict[str, Any]) -> dict[str, Any]:
        return escalations.get(
            _action_id(item),
            {"escalation_level": "normal", "escalation_reasons": [], "recommended_action": "No escalation"},
        )

    critical = [item for item in items if str(escalation_for(item).get("escalation_level", "normal")).lower() == "critical"]
    overdue = [item for item in items if str(escalation_for(item).get("escalation_level", "normal")).lower() == "overdue"]

    st.subheader("Review & Escalation")
    c1, c2 = st.columns(2)
    c1.metric("Critical", len(critical))
    c2.metric("Overdue", len(overdue))
    if not critical and not overdue:
        st.caption("No critical or overdue operator reviews right now.")

    for item in items:
        action_id = _action_id(item)
        state = operator_state_for(item, states)
        escalation = escalation_for(item)
        level = str(escalation.get("escalation_level", "normal") or "normal").upper()
        if level == "NORMAL" and state == "acknowledged":
            continue
        property_id = str(item.get("property_id", "") or "No property ID")
        channel = str(item.get("channel_key", "") or "").replace("_", " ").title()
        with st.expander(f"{level} • {state.replace('_', ' ').title()} • {channel} • {property_id}"):
            reasons = escalation.get("escalation_reasons")
            if isinstance(reasons, list) and reasons:
                st.caption("Escalation: " + ", ".join(str(value).replace("_", " ") for value in reasons))
            age_hours = escalation.get("age_hours")
            if age_hours is not None:
                st.caption(f"Age: {age_hours} hours")
            recommendation = str(escalation.get("recommended_action", "") or "").strip()
            if recommendation:
                st.write(f"**Recommended next action:** {recommendation}")

            saved = states.get(action_id, {})
            note = st.text_input(
                "Internal review note",
                value=str(saved.get("note", "") or ""),
                key=f"my_work_operator_note_{action_id}",
            )
            controls = st.columns(3)
            requested_state: str | None = None
            if controls[0].button("Acknowledge", key=f"my_work_ack_{action_id}", disabled=state == "acknowledged"):
                requested_state = "acknowledged"
            if controls[1].button("Needs follow-up", key=f"my_work_follow_{action_id}", disabled=state == "needs_follow_up"):
                requested_state = "needs_follow_up"
            if controls[2].button("Reopen review", key=f"my_work_reopen_{action_id}", disabled=state == "unacknowledged"):
                requested_state = "unacknowledged"

            if requested_state:
                result = call_function(
                    "commandcore-operator-state",
                    {
                        "action_id": action_id,
                        "dispatch_id": str(item.get("dispatch_id", "") or "").strip(),
                        "property_id": str(item.get("property_id", "") or "").strip(),
                        "channel_key": str(item.get("channel_key", "") or "").strip(),
                        "state": requested_state,
                        "note": note,
                    },
                )
                if result.get("ok"):
                    st.success("Internal review state updated. Readiness and external permissions were not changed.")
                    st.rerun()
                else:
                    st.error("Review state could not be updated. Nothing else was changed.")

            if st.button("Retry internal dispatch", key=f"my_work_retry_{action_id}"):
                payload: dict[str, str] = {"action": "retry_internal_dispatch"}
                queue_object = str(item.get("queue_object", "") or "").strip()
                if queue_object:
                    payload["queue_object"] = queue_object
                else:
                    payload["dispatch_id"] = str(item.get("dispatch_id", "") or "").strip()
                    payload["property_id"] = str(item.get("property_id", "") or "").strip()
                result = call_function("commandcore-operator-action", payload)
                if result.get("ok"):
                    st.success("Internal retry requested. No external action or approval was bypassed.")
                else:
                    st.error("Internal retry was not accepted. Nothing else was changed.")

    st.caption(
        "Operator review controls affect internal acknowledgement/retry only. They do not change readiness, approvals, consent, budgets, legal terms, or external execution permissions."
    )
