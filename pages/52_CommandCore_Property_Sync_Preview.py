from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.commandcore_ux import render_page_header
from cfh_disposition.property_sync_preview import CATEGORIES, load_sync_preview

st.set_page_config(page_title="Property Sync Preview", page_icon="🔎", layout="wide")


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("CommandCore sign-in is not configured yet.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title("Property Sync Preview")
    with st.form("sync_preview_login"):
        entered = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted and password_matches(entered, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("That password did not match.")
    st.stop()


require_password()
render_page_header("Property Sync Preview", "See what the Credit Friendly Homes sheet would change in CommandCore.")
st.info("Preview only. Nothing is imported, updated, deleted, sent, or written to Google Sheets. No deals are created.")
st.caption("Regional inventory, SOLD, and DO NOT SELL LIST are compared with the existing CommandCore properties. Deal links are shown for context.")
st.page_link(Path(__file__).with_name("53_CommandCore_Property_Baseline.py"), label="Final baseline preview", icon="📋")

if st.button("Build read-only preview", type="primary", key="build_sync_preview"):
    st.session_state.pop("property_sync_preview", None)
    try:
        with st.spinner("Reading the sheet and comparing existing properties…"):
            result = load_sync_preview(st.secrets)
    except Exception:  # Never expose provider exceptions, credentials, or private URLs.
        st.error("The complete preview could not be built. Check the Google reader dependencies, source access, and inventory tab names. Nothing was changed.")
    else:
        st.session_state.property_sync_preview = result
        st.session_state.property_sync_preview_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

preview = st.session_state.get("property_sync_preview")
if preview is not None:
    st.caption(f"Snapshot built {st.session_state.property_sync_preview_time}. Rebuild to check for newer changes.")
    for warning in preview.warnings:
        st.warning(warning)
    counts = preview.counts
    for start in (0, 4):
        for column, category in zip(st.columns(4), CATEGORIES[start:start + 4], strict=True):
            column.metric(category.title(), counts[category])
    unchanged = sum(not item.categories for item in preview.items)
    st.caption(f"{unchanged} unchanged. A property can appear in more than one change count.")
    if preview.review_reason_counts:
        with st.expander("Why items need review"):
            st.caption("A row can have several reasons, so these counts overlap.")
            st.dataframe([{"Reason": reason, "Rows": count} for reason, count in preview.review_reason_counts.items()], hide_index=True)
    category = st.selectbox("Show", ("All proposed changes", *CATEGORIES, "UNCHANGED"))
    visible = [item for item in preview.items if (
        bool(item.categories) if category == "All proposed changes" else not item.categories if category == "UNCHANGED" else category in item.categories
    )]
    if not visible:
        st.success("No items in this category.")
    else:
        st.dataframe([{"Property": item.address, "Changes": ", ".join(item.categories) or "UNCHANGED", "Sheet tab": item.tab,
                       "Match": item.match_method, "Review note": item.reason} for item in visible], hide_index=True, use_container_width=True)
        index = st.selectbox("Inspect a property", range(len(visible)), format_func=lambda value: f"{value + 1}. {visible[value].address}")
        item = visible[index]
        st.write(f"**{item.address}**")
        if item.reason:
            st.warning(item.reason)
        st.caption(f"Source: {item.tab or 'Canonical CRM only'}" + (f", row {item.row}" if item.row else ""))
        if item.property_id:
            st.caption(f"Existing property ID: {item.property_id}")
        if item.linked_deals:
            st.caption("Linked existing deal IDs: " + ", ".join(item.linked_deals))
        if item.changes:
            st.dataframe([{"Field": change.field.replace("_", " ").title(), "Current CommandCore": change.current or "Not recorded",
                           "Proposed from sheet": change.proposed or "Blank — review required"} for change in item.changes], hide_index=True, use_container_width=True)
    st.caption("Records changed: 0 · Google writes: 0 · Deals created: 0 · External actions: 0")
