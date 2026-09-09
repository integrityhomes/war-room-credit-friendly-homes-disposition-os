from __future__ import annotations

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.property_change_detection import CHANGE_TYPES
from cfh_disposition.property_change_runtime import read_property_changes

st.set_page_config(page_title="Property Changes", page_icon="🔎", layout="wide")
if not st.session_state.get("authenticated"):
    with st.form("changes_login"):
        password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in")
    expected = configured_password(st.secrets)
    if submitted and expected and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    st.stop()

st.title("Property Changes")
st.caption("Changes to review against CommandCore's recorded properties. Nothing is applied automatically.")
refresh = st.button("Check for changes", key="check_property_changes")
if refresh or "property_detection" not in st.session_state:
    st.session_state.pop("property_detection", None)
    try:
        with st.spinner("Checking the sheet and existing properties…"):
            st.session_state.property_detection = read_property_changes(st.secrets)
    except Exception:
        st.error("The complete check could not finish. No checkpoint was advanced and nothing was changed. Try again.")

result = st.session_state.get("property_detection")
if result is not None:
    st.caption(f"Last checked: {result.checked_at}. Check again for a fresh view.")
    for start in (0, 4):
        for column, kind in zip(st.columns(4), CHANGE_TYPES[start:start + 4], strict=True):
            column.metric(kind.title(), result.counts[kind])
    st.caption(f"{result.unchanged} unchanged · {result.review_rows} source rows excluded for review · {len(result.new_events)} newly detected events this check")
    st.warning("Sold/unavailable is a source-sheet classification, not proof of closing. Missing properties need review and are never automatically sold or deleted.")
    if not result.changes:
        st.success("No eligible property changes to review.")
    else:
        kind = st.selectbox("Show changes", ("All", *CHANGE_TYPES))
        visible = [change for change in result.changes if kind == "All" or kind in change.categories]
        st.dataframe([{"Property": change.evidence.address, "Change": ", ".join(change.categories), "Next step": "Review source facts before approving an update"}
                      for change in visible], hide_index=True)
        if visible:
            selected = st.selectbox("Inspect change", range(len(visible)), format_func=lambda i: visible[i].evidence.address)
            change = visible[selected]
            with st.expander("Source evidence"):
                st.caption(f"Source tab: {change.evidence.tab or 'Not matched'} · Row: {change.evidence.row} · Event: {change.event_id}")
                st.write(change.evidence.reason)
                st.dataframe([{"Field": item.field, "Recorded": item.current, "Sheet": item.proposed} for item in change.evidence.changes], hide_index=True)
    st.caption("Scheduling is not active. Repeat alerts are suppressed in this running server; restart-safe tracking needs an approved checkpoint store.")
    st.caption("Records changed: 0 · Google writes: 0 · Deals created: 0 · External actions: 0")
