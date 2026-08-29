from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Operations Hub", page_icon="🧭", layout="wide")

ACTION_BUCKET = "commandcore-action-queue"
OPERATOR_STATE_BUCKET = "commandcore-operator-state"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Operations Hub")
    st.caption("Private internal access")
    with st.form("commandcore_operations_hub_login"):
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
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required in Streamlit Secrets.")
    return create_client(url, key)


def post_commandcore(function_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        raise RuntimeError("CommandCore services are not configured.")
    req = Request(
        f"{supabase_url}/functions/v1/{function_name}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {service_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CommandCore request was rejected ({exc.code}): {detail[:240]}") from exc
    except URLError as exc:
        raise RuntimeError("CommandCore service could not be reached.") from exc
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise RuntimeError("CommandCore did not confirm the request.")
    return parsed


def load_launch_readiness() -> dict[str, Any]:
    """Read the existing launch-readiness auditor without hiding an unhealthy 503 response."""
    supabase_url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
    service_key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not supabase_url or not service_key:
        raise RuntimeError("CommandCore services are not configured.")
    req = Request(
        f"{supabase_url}/functions/v1/commandcore-launch-readiness",
        data=b"{}",
        method="POST",
        headers={"Authorization": f"Bearer {service_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=30) as response:  # noqa: S310
            parsed = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError as parse_exc:
            raise RuntimeError(f"CommandCore readiness request failed ({exc.code}).") from parse_exc
        if exc.code != 503 or not isinstance(parsed, dict):
            raise RuntimeError(f"CommandCore readiness request failed ({exc.code}).") from exc
    except URLError as exc:
        raise RuntimeError("CommandCore readiness auditor could not be reached.") from exc
    if not isinstance(parsed, dict) or "launch_ready" not in parsed:
        raise RuntimeError("CommandCore readiness auditor returned an invalid response.")
    return parsed


def load_queue_items() -> list[dict[str, Any]]:
    client = get_supabase()
    rows = client.storage.from_(ACTION_BUCKET).list("dispatches") or []
    items: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(ACTION_BUCKET).download(f"dispatches/{name}")
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(parsed, dict):
            continue
        for item in parsed.get("items") if isinstance(parsed.get("items"), list) else []:
            if isinstance(item, dict):
                items.append(item)
    return items


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
        except Exception:
            continue
        if isinstance(parsed, dict):
            action_id = str(parsed.get("action_id", "")).strip()
            if action_id:
                states[action_id] = parsed
    return states


def action_id_for(item: dict[str, Any]) -> str:
    return str(item.get("action_id", "") or f"{item.get('dispatch_id', '')}_{item.get('channel_key', '')}").strip()


def load_human_escalations(items: list[dict[str, Any]], states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:
        return []
    result = post_commandcore("commandcore-aging-escalation", {"items": items, "operator_states": states})
    escalations = result.get("escalations") if isinstance(result.get("escalations"), list) else []
    return [item for item in escalations if isinstance(item, dict)]


def load_coverage_alerts() -> list[dict[str, Any]]:
    result = post_commandcore(
        "commandcore-coverage-exception-ledger",
        {"action": "list", "days": 60, "status": "all"},
    )
    raw = result.get("exceptions") if isinstance(result.get("exceptions"), list) else []
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and str(item.get("status", "")).lower() != "resolved"
        and str(item.get("aging_level", "")).lower() in {"overdue", "escalated", "executive"}
    ]


def human_rows(items: list[dict[str, Any]], escalations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {
        str(item.get("action_id", "")).strip(): item
        for item in escalations
        if str(item.get("action_id", "")).strip()
    }
    rows: list[dict[str, Any]] = []
    for item in items:
        escalation = by_id.get(action_id_for(item), {})
        level = str(escalation.get("escalation_level", "normal")).lower()
        readiness = str(item.get("readiness", "")).upper()
        if level not in {"critical", "overdue"} and readiness not in {"HOLD", "MANUAL", "BLOCKED"}:
            continue
        rows.append(
            {
                "Urgency": level.upper(),
                "Priority": str(item.get("priority", "medium")).upper(),
                "Status": readiness,
                "Property": str(item.get("property_id", "")),
                "Channel": str(item.get("channel_key", "")).replace("_", " ").title(),
                "Age Hours": escalation.get("age_hours"),
                "Dispatch": str(item.get("dispatch_id", "")),
                "Action": " • ".join(str(value) for value in item.get("required_actions", []) if value)
                or "Review item",
            }
        )
    rank = {"CRITICAL": 0, "OVERDUE": 1, "NORMAL": 2}
    rows.sort(key=lambda row: (rank.get(str(row["Urgency"]), 9), 0 if row["Priority"] == "HIGH" else 1))
    return rows


def coverage_rows(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "Urgency": str(item.get("aging_level", "")).upper(),
            "Severity": str(item.get("severity", "")).upper(),
            "Owner": str(item.get("owner_name") or item.get("owner_id") or ""),
            "Age Hours": item.get("age_hours"),
            "Dispatch": str(item.get("dispatch_id", "")),
            "Failure": str(item.get("exception_type") or item.get("type") or "coverage_exception")
            .replace("_", " ")
            .title(),
            "Action": str(item.get("recommended_action") or "Review coverage and confirm safe ownership."),
        }
        for item in alerts
    ]
    rank = {"EXECUTIVE": 0, "ESCALATED": 1, "OVERDUE": 2}
    rows.sort(key=lambda row: (rank.get(str(row["Urgency"]), 9), 0 if row["Severity"] == "CRITICAL" else 1))
    return rows


require_password()

if st.sidebar.button("Log out", key="commandcore_operations_hub_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Operations Hub")
st.caption(
    "One management screen for system readiness, human-work escalations, and aged coverage failures. "
    "READY internal work stays out of the way and continues automatically."
)

readiness: dict[str, Any] | None = None
readiness_error: str | None = None
try:
    readiness = load_launch_readiness()
except Exception as exc:
    readiness_error = str(exc)

st.subheader("CommandCore System Readiness")
if readiness_error:
    st.error(f"System readiness could not be verified: {readiness_error}")
elif readiness is not None:
    launch_ready = readiness.get("launch_ready") is True
    required_count = int(readiness.get("required_service_count") or 0)
    healthy_count = int(readiness.get("healthy_service_count") or 0)
    failed_count = int(readiness.get("failed_required_count") or 0)
    r1, r2, r3 = st.columns(3)
    r1.metric("Critical Chain", "READY" if launch_ready else "NOT READY")
    r2.metric("Healthy Services", f"{healthy_count}/{required_count}")
    r3.metric("Failed Required", failed_count)
    if launch_ready:
        st.success("The required CommandCore operating chain is healthy.")
    else:
        failed_services = readiness.get("failed_required_services")
        failed_names = [str(name) for name in failed_services] if isinstance(failed_services, list) else []
        st.error("CommandCore is not launch-ready. Required service failures need attention before relying on automation.")
        if failed_names:
            st.dataframe(
                [{"Failed Required Service": name} for name in failed_names],
                use_container_width=True,
                hide_index=True,
            )

try:
    queue_items = load_queue_items()
    operator_states = load_operator_states()
    human_escalations = load_human_escalations(queue_items, operator_states)
    coverage_alerts = load_coverage_alerts()
except Exception as exc:
    st.error(f"CommandCore operations data could not be loaded: {exc}")
    st.stop()

human = human_rows(queue_items, human_escalations)
coverage = coverage_rows(coverage_alerts)

human_critical = sum(row["Urgency"] == "CRITICAL" for row in human)
coverage_executive = sum(row["Urgency"] == "EXECUTIVE" for row in coverage)
coverage_escalated = sum(row["Urgency"] == "ESCALATED" for row in coverage)

st.subheader("Management Workload Alerts")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Human Critical", human_critical)
m2.metric("Human Needs Attention", len(human))
m3.metric("Coverage Executive", coverage_executive)
m4.metric("Coverage Escalated", coverage_escalated)
m5.metric("Total Management Alerts", len(human) + len(coverage))

if coverage_executive:
    st.error(f"{coverage_executive} coverage issue(s) require executive attention before normal queue work.")
elif human_critical or coverage_escalated:
    st.warning("Critical or escalated operational work needs management review now.")
else:
    st.success("No executive-level operations alert is currently present.")

left, right = st.columns(2)
with left:
    st.subheader("Human Work Escalations")
    if human:
        st.dataframe(human, use_container_width=True, hide_index=True)
    else:
        st.success("No human-work items currently need escalated management attention.")

with right:
    st.subheader("Coverage Management Alerts")
    if coverage:
        st.dataframe(coverage, use_container_width=True, hide_index=True)
    else:
        st.success("No aged coverage failures currently need management attention.")

st.subheader("Handle These First")
combined: list[dict[str, Any]] = []
for row in coverage:
    urgency_rank = {"EXECUTIVE": 0, "ESCALATED": 1, "OVERDUE": 3}.get(str(row["Urgency"]), 9)
    combined.append({"rank": urgency_rank, "kind": "Coverage", **row})
for row in human:
    urgency_rank = {"CRITICAL": 2, "OVERDUE": 4, "NORMAL": 6}.get(str(row["Urgency"]), 9)
    combined.append({"rank": urgency_rank, "kind": "Human Work", **row})
combined.sort(key=lambda item: int(item.get("rank", 9)))

for item in combined[:10]:
    title = f"{item.get('Urgency', '')} — {item.get('kind', '')} — {item.get('Property') or item.get('Owner') or 'Operational item'}"
    with st.expander(title, expanded=int(item.get("rank", 9)) <= 2):
        if item.get("Dispatch"):
            st.write(f"**Dispatch:** {item['Dispatch']}")
        if item.get("Age Hours") is not None:
            st.write(f"**Age:** {item['Age Hours']} hours")
        if item.get("Failure"):
            st.write(f"**What failed:** {item['Failure']}")
        st.write(f"**Do this next:** {item.get('Action') or 'Review the item.'}")

st.divider()
st.caption(
    "Read-only management visibility. This hub cannot change assignments, approvals, consent, readiness, budgets, "
    "legal terms, payments, communications, or external execution. Use the dedicated CommandCore work and coverage "
    "screens for permitted internal follow-up actions."
)
