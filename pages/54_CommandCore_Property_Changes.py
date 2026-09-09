from __future__ import annotations

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.property_change_detection import CHANGE_TYPES
from cfh_disposition.property_change_review import read_review_proposal, record_review_decision
from cfh_disposition.property_change_runtime import latest_property_check, read_property_changes

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

st.title("Property Change Review")
st.caption("Review what changed, inspect an exact update preview, and decide what needs investigation. Live Apply is disabled.")
refresh = st.button("Check for changes", key="check_property_changes")
# Read shared local evidence on each run; only refresh or first use reads providers.
st.session_state.pop("property_detection", None)
try:
    with st.spinner("Loading the latest property check…"):
        st.session_state.property_detection = read_property_changes(st.secrets, force=refresh)
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
        status = latest_property_check(st.secrets)
        decisions = status.get("review_decisions", {})
        view = st.selectbox("Review status", ("Pending", "Needs investigation", "Ignored", "All"))
        visible = [change for change in result.changes if (kind == "All" or kind in change.categories)
                   and (view == "All" or decisions.get(change.event_id, "Pending") == view)]
        st.dataframe([{"Property": change.evidence.address, "Change type": ", ".join(change.categories),
                       "Source": change.evidence.tab or "Missing from source",
                       "When detected": status.get("change_evidence", {}).get(change.event_id, {}).get("detected_at", result.checked_at),
                       "Recommended action": "Investigate missing or unsafe values; review factual changes"}
                      for change in visible], hide_index=True)
        if visible:
            selected = st.selectbox("Inspect change", range(len(visible)), format_func=lambda i: visible[i].evidence.address)
            change = visible[selected]
            st.subheader(change.evidence.address)
            st.dataframe([{"Field": item.field.replace("_", " ").title(), "Old value": item.current or "Not recorded", "New value": item.proposed or "Blank — never clear automatically"}
                          for item in change.evidence.changes], hide_index=True)
            if st.button("Review", key=f"review_{change.event_id}"):
                st.session_state.pop("property_patch_preview", None)
                try:
                    with st.spinner("Revalidating current source and canonical facts…"):
                        st.session_state.property_patch_preview = read_review_proposal(st.secrets, change.event_id)
                except Exception:
                    st.error("The current records could not be revalidated. No update can be prepared.")
            proposal = st.session_state.get("property_patch_preview")
            if proposal and proposal.event_id == change.event_id:
                for error in proposal.errors:
                    st.warning(error)
                if proposal.new_property:
                    st.info("New property passed baseline validation. Creation remains disabled.")
                    st.json(proposal.new_property)
                elif not proposal.errors:
                    st.info("Exact proposed patch only. It has not been applied.")
                    st.json({"property_id": proposal.property_id, "expected_values": proposal.expected_values,
                             "patch": proposal.patch, "record_fingerprint": proposal.record_fingerprint})
            for label, decision in (("Ignore this detected change", "Ignored"), ("Needs investigation", "Needs investigation"), ("Return to pending", "Pending")):
                if st.button(label, key=f"{decision}_{change.event_id}"):
                    try:
                        record_review_decision(st.secrets, change.event_id, decision)
                        st.rerun()
                    except (ValueError, OSError):
                        st.error("Review decision could not be saved. Reload the current queue.")
            st.caption("Review decisions are local only. Ignoring one event does not hide a different future source change.")
            with st.expander("Source evidence"):
                st.caption(f"Source tab: {change.evidence.tab or 'Not matched'} · Row: {change.evidence.row} · Event: {change.event_id}")
                st.write(change.evidence.reason)
                st.dataframe([{"Field": item.field, "Recorded": item.current, "Sheet": item.proposed} for item in change.evidence.changes], hide_index=True)
    st.caption("Scheduled checks share a local checkpoint across restarts. Only derived change evidence is cached; canonical properties stay in CommandCore.")
    st.caption("Records changed: 0 · Google writes: 0 · Deals created: 0 · External actions: 0")

st.button("Apply safe property update — disabled", disabled=True, key="apply_property_disabled")


@st.fragment(run_every=60)
def watch_scheduled_check():
    # Poll local evidence only; this timer never calls Google or CRM.
    try:
        status = latest_property_check(st.secrets)
    except Exception:
        st.warning("The local check status could not be read.")
        return
    if status.get("error"):
        st.warning(status["error"])
    previous = st.session_state.get("property_check_attempt")
    st.session_state.property_check_attempt = status.get("last_attempt_at")
    if previous and previous != status.get("last_attempt_at"):
        st.rerun()


watch_scheduled_check()
