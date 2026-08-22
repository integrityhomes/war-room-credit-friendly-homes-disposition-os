from __future__ import annotations

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.facebook_assignments_ui import (
    render_facebook_assignment_dashboard,
)
from cfh_disposition.facebook_failure_scan import scan_facebook_operational_failures
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Daily Facebook Posting Assignments",
    page_icon="📋",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("Daily Facebook Posting Assignments")
    st.caption("Private internal access")
    with st.form("facebook_assignment_login"):
        submitted_password = st.text_input("App password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(submitted_password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()


@st.cache_resource
def get_storage():
    return build_storage(st.secrets, SAMPLE_PROPERTIES, SAMPLE_BUYERS)


require_password()
st.title("Daily Facebook Posting Assignment Dashboard")
st.caption(
    "Balanced team assignments, accurate posting records, and automatic cooldown activation."
)

if st.sidebar.button("Log out", key="facebook_assignment_logout"):
    st.session_state.authenticated = False
    st.rerun()

try:
    storage = get_storage()
    properties = storage.list_properties()
except StorageError as exc:
    st.error(f"Properties could not be loaded: {exc}")
    st.stop()

# Any actionable Facebook operational problem discovered here is copied into the
# central critical-failure learning ledger so it will also appear on the main screen.
scan_facebook_operational_failures(st.secrets, properties)

render_facebook_assignment_dashboard(
    properties,
    st.secrets,
    dwelyx_base_url(st.secrets),
)
