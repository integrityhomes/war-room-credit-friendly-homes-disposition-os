from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Workload Audit", page_icon="🧾", layout="wide")

AUDIT_BUCKET = "commandcore-auto-rebalance-audit"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Workload Audit")
    with st.form("commandcore_rebalance_audit_login"):
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


def text(value: Any) -> str:
    return str(value or "").strip()


def load_runs(limit: int = 250) -> list[dict[str, Any]]:
    client = get_supabase()
    try:
        rows = client.storage.from_(AUDIT_BUCKET).list(
            "runs",
            {"limit": limit, "offset": 0, "sortBy": {"column": "name", "order": "desc"}},
        ) or []
    except Exception:
        return []

    runs: list[dict[str, Any]] = []
    for row in rows:
        name = text(row.get("name"))
        if not name.endswith(".json"):
            continue
        try:
            raw = client.storage.from_(AUDIT_BUCKET).download(f"runs/{name}")
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if isinstance(parsed, dict):
            parsed["audit_file"] = name
            runs.append(parsed)
    return runs


def parse_time(value: Any) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


require_password()

if st.sidebar.button("Log out", key="commandcore_rebalance_audit_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Workload Audit")
st.caption(
    "Review what CommandCore moved automatically, what it refused to move, and why. Technical audit identifiers remain available under details."
)

runs = load_runs()

if not runs:
    with st.container(border=True):
        st.markdown("### No automatic workload audit runs yet")
        st.write("This history will populate after the automatic rebalance service completes a production run.")
        left, right = st.columns(2)
        if left.button("Review Workload", type="primary", use_container_width=True):
            st.switch_page("pages/41_CommandCore_Workload_Balance.py")
        if right.button("Review Team Health", use_container_width=True):
            st.switch_page("pages/40_CommandCore_Team_Health.py")
    st.stop()

applied_total = sum(int(run.get("applied_count", 0) or 0) for run in runs)
skipped_total = sum(len(run.get("skipped", [])) for run in runs if isinstance(run.get("skipped"), list))
eligible_total = sum(int(run.get("eligible_low_risk_high_confidence", 0) or 0) for run in runs)
latest_at = parse_time(runs[0].get("generated_at"))
latest_label = latest_at.astimezone().strftime("%b %d, %Y %I:%M %p") if latest_at else "Unknown"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Audit Runs", len(runs))
c2.metric("Eligible Safe Moves", eligible_total)
c3.metric("Automatically Applied", applied_total)
c4.metric("Skipped / Rejected", skipped_total)
st.caption(f"Latest automatic workload review: {latest_label}")

st.subheader("Recent Automatic Workload Reviews")
for index, run in enumerate(runs[:50]):
    generated_at = parse_time(run.get("generated_at"))
    generated_label = generated_at.astimezone().strftime("%b %d, %Y %I:%M %p") if generated_at else text(run.get("generated_at"))
    eligible = int(run.get("eligible_low_risk_high_confidence", 0) or 0)
    applied = int(run.get("applied_count", 0) or 0)
    skipped = run.get("skipped") if isinstance(run.get("skipped"), list) else []
    label = f"{generated_label} • {applied} moved • {len(skipped)} skipped"

    with st.expander(label, expanded=index == 0):
        summary = st.columns(3)
        summary[0].metric("Open Work Scanned", int(run.get("open_items", 0) or 0))
        summary[1].metric("Safe Moves Found", eligible)
        summary[2].metric("Moves Applied", applied)

        applied_rows = run.get("applied") if isinstance(run.get("applied"), list) else []
        if applied_rows:
            st.markdown("**What moved**")
            st.write(f"CommandCore safely reassigned {len(applied_rows)} internal work item(s) in this run.")
        else:
            st.success("No internal assignment needed an automatic move in this run.")

        if skipped:
            st.markdown("**Why some moves were skipped**")
            reason_counts: dict[str, int] = {}
            for item in skipped:
                if not isinstance(item, dict):
                    continue
                reason = text(item.get("reason")).replace("_", " ") or "Unknown reason"
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            for reason, count in sorted(reason_counts.items(), key=lambda pair: (-pair[1], pair[0])):
                st.write(f"• {count} — {reason.title()}")
        else:
            st.caption("No proposed move was rejected during live safety revalidation.")

        with st.expander("Technical audit details", expanded=False):
            st.write(f"**Advisor recommendations:** {int(run.get('advisor_recommendations', 0) or 0)}")
            audit_file = text(run.get("audit_file"))
            if audit_file:
                st.write(f"**Audit file:** {audit_file}")
            if applied_rows:
                st.markdown("**Applied records**")
                for item in applied_rows:
                    if not isinstance(item, dict):
                        continue
                    st.write(
                        f"• From {text(item.get('from_owner_id')) or 'Unknown'} → {text(item.get('to_owner_id')) or 'Unknown'} "
                        f"| Dispatch {text(item.get('dispatch_id')) or 'Unknown'} "
                        f"| Action {text(item.get('action_id')) or 'Unknown'}"
                    )
            if skipped:
                st.markdown("**Skipped records**")
                for item in skipped:
                    if not isinstance(item, dict):
                        continue
                    reason = text(item.get("reason")).replace("_", " ") or "Unknown reason"
                    st.write(
                        f"• Dispatch {text(item.get('dispatch_id')) or 'Unknown'} "
                        f"| Action {text(item.get('action_id')) or 'Unknown'} | {reason}"
                    )

st.divider()
st.caption(
    "Read-only audit visibility. This page cannot change assignments, deal readiness, approvals, consent, budgets, legal terms, payments, communications, or external execution."
)
