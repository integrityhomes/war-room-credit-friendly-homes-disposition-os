from __future__ import annotations

import json
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Operator Dashboard", page_icon="🧭", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"


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


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    actions = item.get("required_actions") if isinstance(item.get("required_actions"), list) else []
    reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
    return {
        "Priority": str(item.get("priority", "medium")).upper(),
        "Status": str(item.get("readiness", "HOLD")).upper(),
        "Channel": str(item.get("channel_key", "")).replace("_", " ").title(),
        "Property ID": str(item.get("property_id", "") or ""),
        "What needs attention": " • ".join(str(a) for a in actions) or "Review item",
        "Reason": ", ".join(str(r).replace("_", " ") for r in reasons),
        "Dispatch ID": str(item.get("dispatch_id", "")),
    }


require_password()

if st.sidebar.button("Log out", key="commandcore_operator_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Operator Dashboard")
st.caption("Only shows work that needs human attention. READY internal work stays out of your way and continues automatically.")

try:
    snapshots = load_queue_snapshots()
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

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Needs Attention", summary["needs_attention"])
c2.metric("HOLD", summary["hold"])
c3.metric("MANUAL", summary["manual"])
c4.metric("BLOCKED", summary["blocked"])
c5.metric("READY / Handled", summary["ready"])

if not snapshots:
    st.info("No CommandCore action-queue snapshots exist yet. The dashboard will populate automatically after campaigns are dispatched.")
    st.stop()

status_filter = st.multiselect("Show statuses", ["HOLD", "MANUAL", "BLOCKED"], default=["HOLD", "MANUAL", "BLOCKED"])
priority_filter = st.multiselect("Show priorities", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM", "LOW"])

filtered = [
    item for item in items
    if str(item.get("readiness", "")).upper() in status_filter
    and str(item.get("priority", "medium")).upper() in priority_filter
]
filtered.sort(key=lambda item: (0 if str(item.get("priority", "")).lower() == "high" else 1, str(item.get("created_at", ""))))

if not filtered:
    st.success("Nothing currently needs attention for the selected filters.")
else:
    st.subheader("Your Action Queue")
    st.dataframe([normalize_item(item) for item in filtered], use_container_width=True, hide_index=True)

    st.subheader("Action Details")
    for item in filtered:
        channel = str(item.get("channel_key", "")).replace("_", " ").title()
        readiness = str(item.get("readiness", "HOLD")).upper()
        priority = str(item.get("priority", "medium")).upper()
        property_id = str(item.get("property_id", "") or "No property ID")
        with st.expander(f"{priority} • {readiness} • {channel} • {property_id}"):
            actions = item.get("required_actions") if isinstance(item.get("required_actions"), list) else []
            for action in actions:
                st.write(f"• {action}")
            reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
            if reasons:
                st.caption("Why: " + ", ".join(str(r).replace("_", " ") for r in reasons))
            lead_url = str(item.get("lead_form_url", "") or "").strip()
            if lead_url:
                st.link_button("Open buyer lead form", lead_url)
            marketing = item.get("marketing_package") if isinstance(item.get("marketing_package"), dict) else {}
            copy = str(marketing.get("copy", marketing.get("body", marketing.get("text", ""))) or "").strip()
            if copy:
                st.text_area("Prepared marketing copy", copy, height=160, disabled=True, key=f"copy_{item.get('action_id','')}")

st.divider()
st.caption("External execution remains disabled. This page is for visibility and human-required actions only.")
