from __future__ import annotations

import json
from typing import Any
from urllib import request

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore My Work", page_icon="👤", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"
HANDOFF_BUCKET = "commandcore-handoff-ledger"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore My Work")
    with st.form("commandcore_my_work_login"):
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


def load_items() -> list[dict[str, Any]]:
    client = get_supabase()
    rows = client.storage.from_(ACTION_BUCKET).list("dispatches") or []
    items: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(ACTION_BUCKET).download(f"dispatches/{name}")
            snapshot = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(snapshot, dict):
            continue
        dispatch_id = str(
            snapshot.get("dispatch_id", "") or name.removesuffix(".json")
        ).strip()
        queue_items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
        for item in queue_items:
            if isinstance(item, dict):
                normalized = dict(item)
                normalized.setdefault("dispatch_id", dispatch_id)
                items.append(normalized)
    return items


@st.cache_data(ttl=60)
def load_handoffs(dispatch_id: str) -> list[dict[str, Any]]:
    dispatch_id = dispatch_id.strip()
    if not dispatch_id:
        return []
    client = get_supabase()
    prefix = f"dispatches/{dispatch_id}"
    try:
        rows = client.storage.from_(HANDOFF_BUCKET).list(prefix) or []
    except Exception:
        return []
    handoffs: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(HANDOFF_BUCKET).download(f"{prefix}/{name}")
            record = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(record, dict):
            handoffs.append(record)
    handoffs.sort(key=lambda record: str(record.get("handoff_at", "")), reverse=True)
    return handoffs


@st.cache_data(ttl=60)
def load_shift_brief(owner_id_value: str) -> dict[str, Any]:
    owner_id_value = owner_id_value.strip()
    if not owner_id_value:
        return {}
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        return {}
    payload = json.dumps({"owner_id": owner_id_value}).encode("utf-8")
    req = request.Request(
        f"{supabase_url}/functions/v1/commandcore-shift-brief",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=20) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def owner_name(item: dict[str, Any]) -> str:
    return str(item.get("owner_name", "") or "Unassigned").strip() or "Unassigned"


def owner_id(item: dict[str, Any]) -> str:
    return str(item.get("owner_id", "") or "").strip()


def action_id(item: dict[str, Any]) -> str:
    explicit = str(item.get("action_id", "") or "").strip()
    if explicit:
        return explicit
    dispatch_id = str(item.get("dispatch_id", "") or "").strip()
    channel = str(item.get("channel_key", "") or "").strip()
    return f"{dispatch_id}_{channel}".strip("_")


def table_row(item: dict[str, Any]) -> dict[str, Any]:
    required_actions = item.get("required_actions", [])
    return {
        "Assigned To": owner_name(item),
        "Priority": str(item.get("priority", "medium")).upper(),
        "Status": str(item.get("readiness", "HOLD")).upper(),
        "Channel": str(item.get("channel_key", "")).replace("_", " ").title(),
        "Property": str(item.get("property_id", "") or ""),
        "Next Action": " • ".join(
            str(value) for value in required_actions if str(value).strip()
        ),
        "Routing Reason": str(item.get("routing_reason", "") or "").replace(
            "_", " "
        ),
        "Reassignment Reason": str(
            item.get("reassignment_reason", "") or ""
        ).replace("_", " "),
        "Reassigned At": str(item.get("reassigned_at", "") or ""),
        "Workload After": item.get("workload_after_assignment"),
    }


def matching_handoffs(item: dict[str, Any]) -> list[dict[str, Any]]:
    dispatch_id = str(item.get("dispatch_id", "") or "").strip()
    target_action_id = action_id(item)
    if not dispatch_id:
        return []
    return [
        record
        for record in load_handoffs(dispatch_id)
        if str(record.get("action_id", "") or "").strip() == target_action_id
    ]


def show_shift_brief(brief: dict[str, Any], selected_name: str) -> None:
    if not brief:
        st.caption("Shift brief is not available yet for this team member.")
        return
    st.subheader(f"{selected_name} Shift Brief")
    st.caption(
        "What was inherited, what needs attention first, and what CommandCore says to do next."
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Open Work", int(brief.get("total_open_work", 0) or 0))
    c2.metric("Urgent", int(brief.get("urgent_count", 0) or 0))
    c3.metric("Inherited", int(brief.get("inherited_count", 0) or 0))
    c4.metric("Blocked", int(brief.get("blocked_count", 0) or 0))
    c5.metric("Manual", int(brief.get("manual_count", 0) or 0))

    brief_items = brief.get("items") if isinstance(brief.get("items"), list) else []
    urgent_items = [item for item in brief_items if isinstance(item, dict) and item.get("urgent")]
    if urgent_items:
        st.warning("These items need attention first.")
        for item in urgent_items:
            property_id = str(item.get("property_id", "") or "No property ID")
            channel = str(item.get("channel_key", "") or "").replace("_", " ").title()
            readiness = str(item.get("readiness", "HOLD") or "HOLD").upper()
            st.markdown(f"**{property_id} • {channel} • {readiness}**")
            actions = item.get("required_actions")
            if isinstance(actions, list) and actions:
                st.write("Next: " + " • ".join(str(value) for value in actions))
            last_handoff = item.get("last_handoff")
            if isinstance(last_handoff, dict):
                previous = str(last_handoff.get("previous_owner_name", "") or "Unassigned")
                reason = str(last_handoff.get("handoff_reason", "") or "routing change").replace(
                    "_", " "
                )
                st.caption(f"Inherited from {previous} because: {reason}")


require_password()

if st.sidebar.button("Log out", key="commandcore_my_work_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore My Work")
st.caption(
    "Shows assigned work, automatic reassignments, full handoff history, and shift briefs."
)

try:
    items = load_items()
except Exception as exc:
    st.error(f"Assigned work could not be loaded: {exc}")
    st.stop()

owners = sorted({owner_name(item) for item in items})
selected_owner = st.selectbox("Whose work?", ["All Team"] + owners)
my_work_only = st.checkbox("My Work view", value=selected_owner != "All Team")

filtered = items
if selected_owner != "All Team" and my_work_only:
    filtered = [item for item in items if owner_name(item) == selected_owner]

if selected_owner != "All Team":
    selected_owner_id = next(
        (owner_id(item) for item in items if owner_name(item) == selected_owner and owner_id(item)),
        "",
    )
    show_shift_brief(load_shift_brief(selected_owner_id), selected_owner)

assigned_count = sum(1 for item in filtered if owner_id(item))
unassigned_count = sum(1 for item in filtered if not owner_id(item))
high_count = sum(
    1 for item in filtered if str(item.get("priority", "")).lower() == "high"
)
reassigned_count = sum(
    1 for item in filtered if str(item.get("reassigned_at", "")).strip()
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Visible Work", len(filtered))
c2.metric("Assigned", assigned_count)
c3.metric("Unassigned", unassigned_count)
c4.metric("High Priority", high_count)
c5.metric("Auto Reassigned", reassigned_count)

if not filtered:
    st.success("No work is currently assigned for this view.")
    st.stop()

st.dataframe([table_row(item) for item in filtered], use_container_width=True, hide_index=True)

st.subheader("Assignment Details")
for item in filtered:
    assigned = owner_name(item)
    channel = str(item.get("channel_key", "")).replace("_", " ").title()
    property_id = str(item.get("property_id", "") or "No property ID")
    with st.expander(f"{assigned} • {channel} • {property_id}"):
        st.write(f"**Assigned to:** {assigned}")
        if owner_id(item):
            st.caption(f"Owner ID: {owner_id(item)}")
        reason = str(
            item.get("routing_reason", "") or "No routing reason recorded"
        ).replace("_", " ")
        st.write(f"**Why CommandCore routed it here:** {reason}")
        reassignment_reason = str(
            item.get("reassignment_reason", "") or ""
        ).replace("_", " ")
        reassigned_at = str(item.get("reassigned_at", "") or "").strip()
        if reassignment_reason:
            st.info(f"Automatically reassigned because: {reassignment_reason}")
        if reassigned_at:
            st.caption(f"Last automatically reassigned: {reassigned_at}")
        score = item.get("routing_score")
        if score is not None:
            st.caption(f"Routing score: {score}")
        workload = item.get("workload_after_assignment")
        if workload is not None:
            st.caption(f"Projected workload after assignment: {workload}")
        actions = item.get("required_actions")
        if isinstance(actions, list) and actions:
            st.write("**What needs to happen:**")
            for action in actions:
                st.write(f"• {action}")

        history = matching_handoffs(item)
        st.write("**Handoff history:**")
        if not history:
            st.caption("No automatic handoffs have been recorded for this task yet.")
        else:
            for record in history:
                previous = str(
                    record.get("previous_owner_name", "") or "Unassigned"
                ).strip()
                new_owner = str(
                    record.get("new_owner_name", "") or record.get("new_owner_id", "")
                ).strip()
                handoff_at = str(record.get("handoff_at", "") or "").strip()
                handoff_reason = str(
                    record.get("handoff_reason", "") or "routing change"
                ).replace("_", " ")
                routing_reason = str(record.get("routing_reason", "") or "").replace(
                    "_", " "
                )
                st.markdown(f"**{previous} → {new_owner}**")
                st.caption(f"{handoff_at} • {handoff_reason}")
                if routing_reason:
                    st.caption(f"Replacement selected because: {routing_reason}")

st.divider()
st.caption(
    "Assignment, shift briefing, rebalancing, and audit history only. These controls never change readiness, approvals, consent, budgets, or external execution permissions."
)
