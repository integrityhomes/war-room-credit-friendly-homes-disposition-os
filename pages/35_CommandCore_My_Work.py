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


def call_commandcore_function(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        return {}
    req = request.Request(
        f"{supabase_url}/functions/v1/{function_name}",
        data=json.dumps(payload).encode("utf-8"),
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
    return call_commandcore_function("commandcore-shift-brief", {"owner_id": owner_id_value})


@st.cache_data(ttl=30)
def load_takeover_history(owner_id_value: str) -> dict[str, Any]:
    owner_id_value = owner_id_value.strip()
    if not owner_id_value:
        return {}
    return call_commandcore_function(
        "commandcore-shift-takeover",
        {"action": "list", "owner_id": owner_id_value},
    )


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


def record_shift_takeover(
    owner_id_value: str,
    selected_name: str,
    brief: dict[str, Any],
    note: str,
) -> dict[str, Any]:
    payload = {
        "action": "takeover",
        "owner_id": owner_id_value,
        "owner_name": selected_name,
        "brief_generated_at": brief.get("generated_at"),
        "open_work_count": brief.get("total_open_work", 0),
        "urgent_count": brief.get("urgent_count", 0),
        "inherited_count": brief.get("inherited_count", 0),
        "blocked_count": brief.get("blocked_count", 0),
        "manual_count": brief.get("manual_count", 0),
        "note": note,
        "source": "commandcore_my_work",
    }
    return call_commandcore_function("commandcore-shift-takeover", payload)


def show_shift_takeover_controls(
    owner_id_value: str,
    selected_name: str,
    brief: dict[str, Any],
) -> None:
    history = load_takeover_history(owner_id_value)
    latest = history.get("latest_takeover") if isinstance(history, dict) else None
    if isinstance(latest, dict):
        taken_at = str(latest.get("taken_over_at", "") or "").strip()
        st.success(f"Last shift takeover recorded: {taken_at}")
        prior_note = str(latest.get("note", "") or "").strip()
        if prior_note:
            st.caption(f"Takeover note: {prior_note}")
    else:
        st.info("No shift takeover has been recorded for this person yet.")

    note = st.text_input(
        "Optional takeover note",
        key=f"takeover_note_{owner_id_value}",
        placeholder="Anything the next person should know",
    )
    if st.button(
        "I received and reviewed this shift",
        type="primary",
        key=f"takeover_{owner_id_value}",
    ):
        result = record_shift_takeover(owner_id_value, selected_name, brief, note)
        if result.get("ok"):
            load_takeover_history.clear()
            st.success("Shift takeover recorded.")
            st.rerun()
        else:
            st.error("Shift takeover could not be recorded. Nothing else was changed.")

    records = history.get("takeovers") if isinstance(history, dict) else []
    if isinstance(records, list) and records:
        with st.expander("Shift takeover history"):
            for record in records[:20]:
                if not isinstance(record, dict):
                    continue
                taken_at = str(record.get("taken_over_at", "") or "").strip()
                counts = (
                    f"Open {int(record.get('open_work_count', 0) or 0)} • "
                    f"Urgent {int(record.get('urgent_count', 0) or 0)} • "
                    f"Inherited {int(record.get('inherited_count', 0) or 0)}"
                )
                st.markdown(f"**{taken_at}**")
                st.caption(counts)


def show_shift_brief(
    brief: dict[str, Any],
    selected_name: str,
    owner_id_value: str,
) -> None:
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
    urgent_items = [
        item for item in brief_items if isinstance(item, dict) and item.get("urgent")
    ]
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
                reason = str(
                    last_handoff.get("handoff_reason", "") or "routing change"
                ).replace("_", " ")
                st.caption(f"Inherited from {previous} because: {reason}")

    st.divider()
    show_shift_takeover_controls(owner_id_value, selected_name, brief)


require_password()

if st.sidebar.button("Log out", key="commandcore_my_work_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore My Work")
st.caption("Start here for assigned work, urgent items, handoffs, and shift takeover.")
nav_left, nav_middle, nav_right = st.columns(3)
with nav_left:
    st.page_link("pages/00_CommandCore.py", label="← Command Center", use_container_width=True)
with nav_middle:
    st.page_link("pages/46_CommandCore_Pipeline_Followup.py", label="Pipeline & Follow-Up", use_container_width=True)
with nav_right:
    st.page_link("pages/45_CommandCore_Deal_Record.py", label="Unified Deal Record", use_container_width=True)

try:
    items = load_items()
except Exception as exc:
    st.error(f"Assigned work could not be loaded: {exc}")
    st.stop()

owners = sorted({owner_name(item) for item in items})
selected_owner = st.selectbox("Show work for", ["All Team"] + owners)

filtered = items
if selected_owner != "All Team":
    filtered = [item for item in items if owner_name(item) == selected_owner]
    selected_owner_id = next(
        (
            owner_id(item)
            for item in items
            if owner_name(item) == selected_owner and owner_id(item)
        ),
        "",
    )
    show_shift_brief(
        load_shift_brief(selected_owner_id),
        selected_owner,
        selected_owner_id,
    )

assigned_count = sum(1 for item in filtered if owner_id(item))
unassigned_count = sum(1 for item in filtered if not owner_id(item))
high_count = sum(
    1 for item in filtered if str(item.get("priority", "")).lower() == "high"
)
reassigned_count = sum(
    1 for item in filtered if str(item.get("reassigned_at", "")).strip()
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Open Work", len(filtered))
c2.metric("Assigned", assigned_count)
c3.metric("Unassigned", unassigned_count)
c4.metric("High Priority", high_count)
c5.metric("Reassigned", reassigned_count)

if not filtered:
    with st.container(border=True):
        st.markdown("### You're caught up for this view")
        st.write("There is no assigned CommandCore work here right now.")
        next_left, next_right = st.columns(2)
        if next_left.button("Review Follow-Up & Pipeline", type="primary", use_container_width=True):
            st.switch_page("pages/46_CommandCore_Pipeline_Followup.py")
        if next_right.button("Add New Lead", use_container_width=True):
            st.switch_page("pages/44_CommandCore_CRM.py")
        st.caption("CommandCore will place new assigned work here automatically when it needs human attention.")
    st.stop()

st.subheader("What needs attention")
st.dataframe([table_row(item) for item in filtered], use_container_width=True, hide_index=True)

st.subheader("Work Details")
for item in filtered:
    assigned = owner_name(item)
    channel = str(item.get("channel_key", "")).replace("_", " ").title()
    property_id = str(item.get("property_id", "") or "No property ID")
    item_action_id = action_id(item) or f"{assigned}_{channel}_{property_id}"
    with st.expander(f"{assigned} • {channel} • {property_id}"):
        actions = item.get("required_actions")
        if isinstance(actions, list) and actions:
            st.write("**What needs to happen next:**")
            for action in actions:
                st.write(f"• {action}")
        else:
            st.caption("No next action has been recorded yet.")

        reassignment_reason = str(
            item.get("reassignment_reason", "") or ""
        ).replace("_", " ")
        reassigned_at = str(item.get("reassigned_at", "") or "").strip()
        if reassignment_reason:
            st.info(f"Automatically reassigned because: {reassignment_reason}")
        if reassigned_at:
            st.caption(f"Last reassigned: {reassigned_at}")

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
                st.markdown(f"**{previous} → {new_owner}**")
                st.caption(f"{handoff_at} • {handoff_reason}")

        if st.toggle("Show routing details", key=f"routing_details_{item_action_id}"):
            st.caption(f"Assigned to: {assigned}")
            if owner_id(item):
                st.caption(f"Owner ID: {owner_id(item)}")
            reason = str(
                item.get("routing_reason", "") or "No routing reason recorded"
            ).replace("_", " ")
            st.caption(f"Routing reason: {reason}")
            score = item.get("routing_score")
            if score is not None:
                st.caption(f"Routing score: {score}")
            workload = item.get("workload_after_assignment")
            if workload is not None:
                st.caption(f"Projected workload after assignment: {workload}")

st.divider()
st.caption(
    "Assignment, shift briefing, takeover tracking, rebalancing, and audit history only. These controls never change readiness, approvals, consent, budgets, or external execution permissions."
)
