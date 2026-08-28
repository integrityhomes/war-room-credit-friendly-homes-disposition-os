from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Operator Dashboard", page_icon="🧭", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"
OPERATOR_STATE_BUCKET = "commandcore-operator-state"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Operator Dashboard")
    st.caption("Private internal access")
    with st.form("commandcore_operator_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
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
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in Streamlit Secrets.")
    return create_client(url, key)


def load_queue_snapshots() -> list[dict[str, Any]]:
    client = get_supabase()
    rows = client.storage.from_(ACTION_BUCKET).list("dispatches") or []
    snapshots: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(ACTION_BUCKET).download(f"dispatches/{name}")
            parsed = json.loads(raw.decode("utf-8"))
            if isinstance(parsed, dict):
                snapshots.append(parsed)
        except Exception:
            continue
    snapshots.sort(key=lambda item: str(item.get("generated_at", "")), reverse=True)
    return snapshots


def load_operator_states() -> dict[str, dict[str, Any]]:
    client = get_supabase()
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
            if not isinstance(parsed, dict):
                continue
            action_id = str(parsed.get("action_id", "")).strip()
            if action_id:
                states[action_id] = parsed
        except Exception:
            continue
    return states


def action_id_for(item: dict[str, Any]) -> str:
    return str(item.get("action_id", "") or f"{item.get('dispatch_id', '')}_{item.get('channel_key', '')}").strip()


def operator_state_for(item: dict[str, Any], states: dict[str, dict[str, Any]]) -> str:
    state = states.get(action_id_for(item), {})
    return str(state.get("state", "unacknowledged") or "unacknowledged").strip().lower()


def post_commandcore_function(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    service_role_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_role_key:
        raise RuntimeError("CommandCore operator services are not configured.")

    request = Request(
        f"{supabase_url}/functions/v1/{function_name}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CommandCore request was rejected ({exc.code}): {detail[:240]}") from exc
    except URLError as exc:
        raise RuntimeError("CommandCore service could not be reached.") from exc

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise RuntimeError("CommandCore did not confirm the requested internal action.")
    return parsed


def evaluate_escalations(
    items: list[dict[str, Any]], operator_states: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    result = post_commandcore_function(
        "commandcore-aging-escalation",
        {"items": items, "operator_states": operator_states},
    )
    escalations = result.get("escalations") if isinstance(result.get("escalations"), list) else []
    return {
        str(record.get("action_id", "")): record
        for record in escalations
        if isinstance(record, dict) and str(record.get("action_id", "")).strip()
    }


def escalation_for(item: dict[str, Any], escalations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return escalations.get(
        action_id_for(item),
        {"escalation_level": "normal", "escalation_reasons": [], "recommended_action": "No escalation"},
    )


def normalize_item(
    item: dict[str, Any], states: dict[str, dict[str, Any]], escalations: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    actions = item.get("required_actions") if isinstance(item.get("required_actions"), list) else []
    reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
    state = operator_state_for(item, states)
    escalation = escalation_for(item, escalations)
    return {
        "Escalation": str(escalation.get("escalation_level", "normal")).upper(),
        "Priority": str(item.get("priority", "medium")).upper(),
        "Status": str(item.get("readiness", "HOLD")).upper(),
        "Review State": state.replace("_", " ").title(),
        "Channel": str(item.get("channel_key", "")).replace("_", " ").title(),
        "Property ID": str(item.get("property_id", "") or ""),
        "What needs attention": " • ".join(str(a) for a in actions) or "Review item",
        "Reason": ", ".join(str(r).replace("_", " ") for r in reasons),
        "Age Hours": escalation.get("age_hours"),
        "Dispatch ID": str(item.get("dispatch_id", "")),
    }


def retry_internal_dispatch(item: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, str] = {"action": "retry_internal_dispatch"}
    queue_object = str(item.get("queue_object", "") or "").strip()
    if queue_object:
        payload["queue_object"] = queue_object
    else:
        payload["dispatch_id"] = str(item.get("dispatch_id", "") or "").strip()
        payload["property_id"] = str(item.get("property_id", "") or "").strip()
    return post_commandcore_function("commandcore-operator-action", payload)


def save_operator_state(item: dict[str, Any], state: str, note: str = "") -> dict[str, Any]:
    payload = {
        "action_id": action_id_for(item),
        "dispatch_id": str(item.get("dispatch_id", "") or "").strip(),
        "property_id": str(item.get("property_id", "") or "").strip(),
        "channel_key": str(item.get("channel_key", "") or "").strip(),
        "state": state,
        "note": note,
    }
    return post_commandcore_function("commandcore-operator-state", payload)


require_password()

if st.sidebar.button("Log out", key="commandcore_operator_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Operator Dashboard")
st.caption("Only shows work that needs human attention. READY internal work stays out of your way and continues automatically.")

try:
    snapshots = load_queue_snapshots()
    operator_states = load_operator_states()
except Exception as exc:
    st.error(f"CommandCore action queue could not be loaded: {exc}")
    st.stop()

summary = {"ready": 0, "hold": 0, "manual": 0, "blocked": 0, "needs_attention": 0}
items: list[dict[str, Any]] = []
for snapshot in snapshots:
    snap_summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    for key in summary:
        summary[key] += int(snap_summary.get(key, 0) or 0)
    raw_items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
    for raw in raw_items:
        if isinstance(raw, dict):
            items.append(raw)

try:
    escalations = evaluate_escalations(items, operator_states) if items else {}
except Exception as exc:
    st.warning(f"Aging and escalation could not be refreshed: {exc}")
    escalations = {}

critical_count = sum(
    1 for item in items if str(escalation_for(item, escalations).get("escalation_level", "normal")) == "critical"
)
overdue_count = sum(
    1 for item in items if str(escalation_for(item, escalations).get("escalation_level", "normal")) == "overdue"
)

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("CRITICAL", critical_count)
c2.metric("OVERDUE", overdue_count)
c3.metric("Needs Attention", summary["needs_attention"])
c4.metric("HOLD", summary["hold"])
c5.metric("MANUAL", summary["manual"])
c6.metric("BLOCKED", summary["blocked"])
c7.metric("READY / Handled", summary["ready"])

if critical_count:
    st.error(f"{critical_count} critical item(s) need review now.")
elif overdue_count:
    st.warning(f"{overdue_count} overdue item(s) need follow-up.")

if not snapshots:
    st.info("No CommandCore action-queue snapshots exist yet. The dashboard will populate automatically after campaigns are dispatched.")
    st.stop()

status_filter = st.multiselect("Show statuses", ["HOLD", "MANUAL", "BLOCKED"], default=["HOLD", "MANUAL", "BLOCKED"])
priority_filter = st.multiselect("Show priorities", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM", "LOW"])
review_filter = st.multiselect(
    "Show review states",
    ["UNACKNOWLEDGED", "NEEDS FOLLOW UP", "ACKNOWLEDGED"],
    default=["UNACKNOWLEDGED", "NEEDS FOLLOW UP", "ACKNOWLEDGED"],
)
escalation_filter = st.multiselect(
    "Show escalation levels",
    ["CRITICAL", "OVERDUE", "NORMAL"],
    default=["CRITICAL", "OVERDUE", "NORMAL"],
)

filtered = [
    item
    for item in items
    if str(item.get("readiness", "")).upper() in status_filter
    and str(item.get("priority", "medium")).upper() in priority_filter
    and operator_state_for(item, operator_states).replace("_", " ").upper() in review_filter
    and str(escalation_for(item, escalations).get("escalation_level", "normal")).upper() in escalation_filter
]
escalation_rank = {"critical": 0, "overdue": 1, "normal": 2}
filtered.sort(
    key=lambda item: (
        escalation_rank.get(str(escalation_for(item, escalations).get("escalation_level", "normal")), 2),
        0 if operator_state_for(item, operator_states) == "unacknowledged" else 1,
        0 if str(item.get("priority", "")).lower() == "high" else 1,
        str(item.get("created_at", "")),
    )
)

if not filtered:
    st.success("Nothing currently needs attention for the selected filters.")
else:
    st.subheader("Your Action Queue")
    st.dataframe(
        [normalize_item(item, operator_states, escalations) for item in filtered],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Action Details")
    for item in filtered:
        channel = str(item.get("channel_key", "")).replace("_", " ").title()
        readiness = str(item.get("readiness", "HOLD")).upper()
        priority = str(item.get("priority", "medium")).upper()
        property_id = str(item.get("property_id", "") or "No property ID")
        action_id = action_id_for(item)
        review_state = operator_state_for(item, operator_states)
        escalation = escalation_for(item, escalations)
        escalation_level = str(escalation.get("escalation_level", "normal")).upper()
        with st.expander(
            f"{escalation_level} • {priority} • {readiness} • "
            f"{review_state.replace('_', ' ').title()} • {channel} • {property_id}"
        ):
            if escalation_level == "CRITICAL":
                st.error("Critical: review this item now.")
            elif escalation_level == "OVERDUE":
                st.warning("Overdue: follow-up is due.")
            escalation_reasons = escalation.get("escalation_reasons")
            if isinstance(escalation_reasons, list) and escalation_reasons:
                st.caption("Escalation: " + ", ".join(str(r).replace("_", " ") for r in escalation_reasons))
            age_hours = escalation.get("age_hours")
            if age_hours is not None:
                st.caption(f"Age: {age_hours} hours")

            actions = item.get("required_actions") if isinstance(item.get("required_actions"), list) else []
            for action in actions:
                st.write(f"• {action}")
            reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
            if reasons:
                st.caption("Why: " + ", ".join(str(r).replace("_", " ") for r in reasons))

            state_record = operator_states.get(action_id, {})
            saved_note = str(state_record.get("note", "") or "").strip()
            note = st.text_input("Internal note", value=saved_note, key=f"note_{action_id}")
            s1, s2, s3 = st.columns(3)
            if s1.button("Acknowledge", key=f"ack_{action_id}", disabled=review_state == "acknowledged"):
                try:
                    save_operator_state(item, "acknowledged", note)
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("Marked acknowledged. Readiness and external gates were not changed.")
                    st.rerun()
            if s2.button("Needs follow-up", key=f"follow_{action_id}", disabled=review_state == "needs_follow_up"):
                try:
                    save_operator_state(item, "needs_follow_up", note)
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("Marked for follow-up. The underlying action remains unresolved until its real gate is satisfied.")
                    st.rerun()
            if s3.button("Reopen review", key=f"reopen_{action_id}", disabled=review_state == "unacknowledged"):
                try:
                    save_operator_state(item, "unacknowledged", note)
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("Returned to unacknowledged.")
                    st.rerun()

            if readiness == "HOLD":
                st.caption("Safe option: retry CommandCore's internal processing. This cannot approve, send, post, or spend money.")
                if st.button("Retry internal processing", key=f"retry_{action_id}"):
                    with st.spinner("CommandCore is retrying the internal workflow..."):
                        try:
                            result = retry_internal_dispatch(item)
                        except Exception as exc:
                            st.error(str(exc))
                        else:
                            st.success("Internal retry completed. No external action was started.")
                            if result.get("safe_internal_retry_completed"):
                                st.rerun()

            lead_url = str(item.get("lead_form_url", "") or "").strip()
            if lead_url:
                st.link_button("Open buyer lead form", lead_url)
            marketing = item.get("marketing_package") if isinstance(item.get("marketing_package"), dict) else {}
            copy = str(marketing.get("copy", marketing.get("body", marketing.get("text", ""))) or "").strip()
            if copy:
                st.text_area("Prepared marketing copy", copy, height=160, disabled=True, key=f"copy_{action_id}")

st.divider()
st.caption(
    "Aging and acknowledgment are tracking only. They never change READY/HOLD/MANUAL/BLOCKED status. "
    "Safe internal retries are allowed; approvals, sends, posts, consent changes, connection changes, "
    "and ad spend remain gated."
)
