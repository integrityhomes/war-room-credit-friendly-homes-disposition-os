from __future__ import annotations

import json
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore My Work", page_icon="👤", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"


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
        queue_items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
        for item in queue_items:
            if isinstance(item, dict):
                items.append(item)
    return items


def owner_name(item: dict[str, Any]) -> str:
    return str(item.get("owner_name", "") or "Unassigned").strip() or "Unassigned"


def owner_id(item: dict[str, Any]) -> str:
    return str(item.get("owner_id", "") or "").strip()


def table_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "Assigned To": owner_name(item),
        "Priority": str(item.get("priority", "medium")).upper(),
        "Status": str(item.get("readiness", "HOLD")).upper(),
        "Channel": str(item.get("channel_key", "")).replace("_", " ").title(),
        "Property": str(item.get("property_id", "") or ""),
        "Next Action": " • ".join(str(v) for v in item.get("required_actions", []) if str(v).strip()),
        "Routing Reason": str(item.get("routing_reason", "") or "").replace("_", " "),
        "Workload After": item.get("workload_after_assignment"),
    }


require_password()

if st.sidebar.button("Log out", key="commandcore_my_work_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore My Work")
st.caption("Shows human-required work already assigned by CommandCore. This page cannot approve, send, post, or spend money.")

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

assigned_count = sum(1 for item in filtered if owner_id(item))
unassigned_count = sum(1 for item in filtered if not owner_id(item))
high_count = sum(1 for item in filtered if str(item.get("priority", "")).lower() == "high")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Visible Work", len(filtered))
c2.metric("Assigned", assigned_count)
c3.metric("Unassigned", unassigned_count)
c4.metric("High Priority", high_count)

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
        reason = str(item.get("routing_reason", "") or "No routing reason recorded").replace("_", " ")
        st.write(f"**Why CommandCore routed it here:** {reason}")
        score = item.get("routing_score")
        if score is not None:
            st.caption(f"Routing score: {score}")
        workload = item.get("workload_after_assignment")
        if workload is not None:
            st.caption(f"Projected workload after assignment: {workload}")
        actions = item.get("required_actions") if isinstance(item.get("required_actions"), list) else []
        if actions:
            st.write("**What needs to happen:**")
            for action in actions:
                st.write(f"• {action}")

st.divider()
st.caption("Assignment is routing only. It never changes readiness, approvals, consent, budgets, or external execution permissions.")
