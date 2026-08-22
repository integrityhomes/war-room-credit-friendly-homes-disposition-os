from __future__ import annotations

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.record_manager import render_record_manager
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Record Manager",
    page_icon="🏠",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("Record Manager")
    st.caption("Private internal access")
    with st.form("record_manager_login"):
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
st.title("Record Manager")
st.caption(
    "Central property and buyer records. Locked marketing facts must be changed here, not on downstream marketing screens."
)

if st.sidebar.button("Log out", key="record_manager_logout"):
    st.session_state.authenticated = False
    st.rerun()

try:
    storage = get_storage()
except StorageError as exc:
    st.error(f"Storage could not be loaded: {exc}")
    st.stop()

render_record_manager(storage)
