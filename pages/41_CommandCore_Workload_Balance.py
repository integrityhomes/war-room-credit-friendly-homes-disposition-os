from __future__ import annotations

import json
from typing import Any
from urllib import request

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Workload Balance", page_icon="⚖️", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Workload Balance")
    with st.form("commandcore_workload_balance_login"):
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


def call_commandcore(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        return {}
    req = request.Request(
        f"{supabase_url}/functions/v1/{function_name}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {service_key}", "Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_open_items() -> list[dict[str, Any]]:
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
        dispatch_id = str(snapshot.get("dispatch_id", "") or name.removesuffix(".json")).strip()
        queue_items = snapshot.get("items") if isinstance(snapshot.get("items"), list) else []
        for item in queue_items:
            if not isinstance(item, dict):
                continue
            readiness = str(item.get("readiness", "")).strip().lower()
            if readiness not in {"hold", "manual", "blocked"}:
                continue
            normalized = dict(item)
            normalized.setdefault("dispatch_id", dispatch_id)
            items.append(normalized)
    return items


def recommendation_label(item: dict[str, Any]) -> str:
    channel = str(item.get("channel_key", "")).replace("_", " ").title()
    return (
        f"{item.get('from_owner_name', 'Unknown')} → {item.get('to_owner_name', 'Unknown')}"
        + (f" • {channel}" if channel else "")
    )


require_password()

if st.sidebar.button("Log out", key="commandcore_workload_balance_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Workload Balance")
st.caption(
    "Finds overloaded team members, recommends the safest internal moves, and revalidates every move before applying it."
)

try:
    open_items = load_open_items()
except Exception as exc:
    st.error(f"Open work could not be loaded: {exc}")
    st.stop()

result = call_commandcore("commandcore-workload-balance-advisor", {"items": open_items})
recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []
recommendations = [item for item in recommendations if isinstance(item, dict)]

c1, c2, c3 = st.columns(3)
c1.metric("Open Work", int(result.get("open_items", len(open_items)) or 0))
c2.metric("Overloaded Team Members", int(result.get("overloaded_team_members", 0) or 0))
c3.metric("Safe Moves Recommended", len(recommendations))

if not recommendations:
    with st.container(border=True):
        st.markdown("### No workload move is recommended right now")
        st.write("CommandCore does not currently see a safe internal reassignment that would improve workload balance.")
        left, right = st.columns(2)
        if left.button("Review Team Health", type="primary", use_container_width=True):
            st.switch_page("pages/40_CommandCore_Team_Health.py")
        if right.button("Review My Work", use_container_width=True):
            st.switch_page("pages/35_CommandCore_My_Work.py")
    st.stop()

st.subheader("Recommended Internal Moves")
for index, recommendation in enumerate(recommendations):
    confidence = str(recommendation.get("confidence", "medium")).upper()
    label = recommendation_label(recommendation)
    with st.expander(f"{confidence} • {label}", expanded=index == 0):
        left, right = st.columns(2)
        left.write(
            f"**Move from:** {recommendation.get('from_owner_name', '')} "
            f"({int(recommendation.get('from_load_percent', 0) or 0)}% load)"
        )
        right.write(
            f"**Move to:** {recommendation.get('to_owner_name', '')} "
            f"({int(recommendation.get('to_load_percent_before', 0) or 0)}% → "
            f"{int(recommendation.get('to_load_percent_after', 0) or 0)}%)"
        )
        channel = str(recommendation.get("channel_key", "")).replace("_", " ").title()
        if channel:
            st.write(f"**Work type:** {channel}")
        st.write(f"**Why CommandCore chose this move:** {recommendation.get('reason', '')}")
        st.caption(
            "Before applying, CommandCore re-checks the current owner, open-work status, target availability, activity, and capacity."
        )

        confirmed = st.checkbox(
            "Approve this internal workload move",
            key=f"confirm_rebalance_{index}_{recommendation.get('action_id', '')}",
        )
        if st.button(
            "Apply Safe Rebalance",
            type="primary",
            disabled=not confirmed,
            key=f"apply_rebalance_{index}_{recommendation.get('action_id', '')}",
        ):
            applied = call_commandcore(
                "commandcore-safe-rebalance-apply",
                {
                    "apply": True,
                    "dispatch_id": recommendation.get("dispatch_id"),
                    "action_id": recommendation.get("action_id"),
                    "from_owner_id": recommendation.get("from_owner_id"),
                    "to_owner_id": recommendation.get("to_owner_id"),
                    "reason": recommendation.get("reason") or "workload_balance_advisor",
                },
            )
            if applied.get("ok") and applied.get("applied"):
                st.success("Internal workload move applied and recorded in the Handoff Ledger.")
                st.rerun()
            else:
                error = str(applied.get("error", "recommendation could not be applied"))
                st.warning(
                    "CommandCore did not move the work because the recommendation was no longer safe or current. "
                    f"Reason: {error.replace('_', ' ')}."
                )

        technical = {
            "Property ID": recommendation.get("property_id"),
            "Dispatch ID": recommendation.get("dispatch_id"),
            "Action ID": recommendation.get("action_id"),
        }
        if any(value for value in technical.values()):
            with st.expander("Technical details", expanded=False):
                for name, value in technical.items():
                    if value:
                        st.write(f"**{name}:** {value}")

st.divider()
st.caption(
    "Assignment-only control. This page cannot change deal readiness, approvals, consent, budgets, legal terms, "
    "payments, communications, or external execution."
)
