from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from supabase import create_client

st.set_page_config(page_title="CommandCore Rebalance Audit", page_icon="🧾", layout="wide")

AUDIT_BUCKET = "commandcore-auto-rebalance-audit"


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("CommandCore Rebalance Audit")
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
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


require_password()

if st.sidebar.button("Log out", key="commandcore_rebalance_audit_logout"):
    st.session_state.authenticated = False
    st.rerun()

st.title("CommandCore Automatic Rebalance Audit")
st.caption(
    "Shows what CommandCore considered, what it moved automatically, and what it skipped during strict low-risk workload balancing."
)

runs = load_runs()

if not runs:
    st.info(
        "No automatic rebalance audit runs are stored yet. The hourly schedule will populate this page after its next production run."
    )
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

st.caption(f"Latest recorded run: {latest_label}")

summary_rows: list[dict[str, Any]] = []
for run in runs:
    generated = parse_time(run.get("generated_at"))
    summary_rows.append(
        {
            "Run Time": generated.astimezone().strftime("%Y-%m-%d %I:%M %p") if generated else "Unknown",
            "Open Work": int(run.get("open_items", 0) or 0),
            "Advisor Recommendations": int(run.get("advisor_recommendations", 0) or 0),
            "Eligible": int(run.get("eligible_low_risk_high_confidence", 0) or 0),
            "Applied": int(run.get("applied_count", 0) or 0),
            "Skipped": len(run.get("skipped", [])) if isinstance(run.get("skipped"), list) else 0,
            "Audit File": text(run.get("audit_file")),
        }
    )

st.subheader("Recent Automatic Runs")
st.dataframe(summary_rows, use_container_width=True, hide_index=True)

st.subheader("Run Details")
for index, run in enumerate(runs[:50]):
    generated = parse_time(run.get("generated_at"))
    run_label = generated.astimezone().strftime("%b %d, %Y %I:%M %p") if generated else text(run.get("audit_file"))
    applied = run.get("applied") if isinstance(run.get("applied"), list) else []
    skipped = run.get("skipped") if isinstance(run.get("skipped"), list) else []
    eligible = run.get("eligible") if isinstance(run.get("eligible"), list) else []

    with st.expander(
        f"{run_label} — {len(applied)} applied / {len(skipped)} skipped",
        expanded=index == 0,
    ):
        st.write(
            f"**Open work:** {int(run.get('open_items', 0) or 0)}  |  "
            f"**Advisor recommendations:** {int(run.get('advisor_recommendations', 0) or 0)}  |  "
            f"**Eligible low-risk moves:** {len(eligible)}"
        )

        if applied:
            st.write("**Automatically applied**")
            applied_rows = []
            for item in applied:
                if not isinstance(item, dict):
                    continue
                applied_rows.append(
                    {
                        "Dispatch": text(item.get("dispatch_id")),
                        "Action": text(item.get("action_id")),
                        "From": text(item.get("from_owner_id")),
                        "To": text(item.get("to_owner_id")),
                        "Applied": item.get("applied") is True,
                    }
                )
            if applied_rows:
                st.dataframe(applied_rows, use_container_width=True, hide_index=True)

        if skipped:
            st.write("**Skipped or rejected after revalidation**")
            skipped_rows = []
            for item in skipped:
                if not isinstance(item, dict):
                    continue
                skipped_rows.append(
                    {
                        "Dispatch": text(item.get("dispatch_id")),
                        "Action": text(item.get("action_id")),
                        "Reason": text(item.get("reason")).replace("_", " "),
                    }
                )
            if skipped_rows:
                st.dataframe(skipped_rows, use_container_width=True, hide_index=True)

        if not applied and not skipped:
            st.caption("This run did not make or reject any automatic assignment move.")

st.divider()
st.caption(
    "Read-only audit visibility. This page cannot change assignments, readiness, approvals, consent, budgets, legal terms, payments, communications, or external execution."
)
