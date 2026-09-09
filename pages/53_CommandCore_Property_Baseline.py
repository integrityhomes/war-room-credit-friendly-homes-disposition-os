from __future__ import annotations

import traceback

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_ux import render_page_header
from cfh_disposition.property_baseline import load_baseline_preview

st.set_page_config(page_title="Final Property Baseline", page_icon="📋", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("CommandCore sign-in is not configured yet.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Final Property Baseline")
    with st.form("baseline_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("That password did not match.")
    st.stop()


require_password()
render_page_header("Final Property Baseline", "Inspect the exact property records proposed for the first CommandCore load.")
st.info("Import is disabled. This screen reads and prepares a summary only. No properties or deals are saved.")
st.caption(
    "Prior validation reference: 155 properties — 29 active, 126 source-classified sold/unavailable, and 300 Needs Review rows excluded. "
    "Build the summary to verify the current source; these reference counts are not a live read."
)

if st.button("Build pre-import summary", type="primary", key="build_property_baseline"):
    st.session_state.pop("property_baseline_plan", None)
    try:
        with st.spinner("Reading one sheet snapshot and checking canonical properties…"):
            plan = load_baseline_preview(st.secrets)
    except Exception as exc:
        st.error("The complete baseline could not be read. Nothing was imported. Check source access and try again.")
        # Exception messages, source lines and locals can contain provider secrets.
        # Keep only the error type and function/line locations for diagnosis.
        with st.expander("Read failure details"):
            st.code(type(exc).__name__ + " | " + " > ".join(
                f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(exc.__traceback__)
            ))
    else:
        st.session_state.property_baseline_plan = plan

plan = st.session_state.get("property_baseline_plan")
if plan is not None:
    st.caption(f"Read at {plan.observed_at}. Rebuild before reviewing a newer sheet version.")
    metrics = (
        ("Properties proposed for creation", len(plan.properties)), ("Active inventory", plan.active_count),
        ("Source-classified sold / unavailable", plan.sold_count), ("Skipped Needs Review", plan.skipped_review),
        ("Duplicate candidates prevented", plan.duplicates_prevented), ("Errors", len(plan.errors)), ("Deletions", plan.deletions),
    )
    for start in (0, 4):
        group = metrics[start:start + 4]
        for column, (label, count) in zip(st.columns(len(group)), group, strict=True):
            column.metric(label, count)
    st.caption("Duplicate count is the number of source rows withheld for duplicate identities or existing canonical matches; it may overlap skipped review rows.")
    for error in plan.errors:
        st.error(error)
    if not plan.errors:
        st.success("The fresh summary matches the validated totals. It is ready for inspection, not import.")
    st.warning("Sold/unavailable is the source sheet's classification. It does not verify a completed closing or create a closed deal.")
    if plan.properties:
        st.dataframe([{"Property": item.address, "Source tab": item.tab, "Classification": item.record["availability"],
                       "Identity": item.identity_method} for item in plan.properties], hide_index=True, width="stretch")
        selected = st.selectbox("Inspect a proposed property", range(len(plan.properties)), format_func=lambda index: plan.properties[index].address)
        item = plan.properties[selected]
        with st.expander("Exact proposed canonical record", expanded=True):
            st.json(item.record)
    st.caption("Snapshot fingerprint: " + plan.snapshot_hash)
    st.caption("This identifies the exact proposed content. Matching totals alone do not authorize an import.")
    st.button("Import baseline — disabled", disabled=True, key="baseline_import_disabled")
    st.caption("Records written: 0 · Existing records updated: 0 · Deals created: 0 · Deletions: 0 · Google writes: 0")
