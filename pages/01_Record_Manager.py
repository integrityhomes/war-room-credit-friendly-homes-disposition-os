from __future__ import annotations

import streamlit as st

from cfh_disposition.app_secrets import get_secrets
from cfh_disposition.auth import require_password
from cfh_disposition.record_manager_safe import render_record_manager
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Property & Buyer Records",
    page_icon="🏠",
    layout="wide",
)

@st.cache_resource
def get_storage():
    return build_storage(get_secrets(), SAMPLE_PROPERTIES, SAMPLE_BUYERS)

require_password()
st.title("Property & Buyer Records")
st.caption(
    "Review the property facts used by marketing and maintain buyer contact records in one controlled workspace."
)
st.info(
    "Property facts saved here are the source of truth for downstream marketing. "
    "Changing a fact here does not publish or send anything by itself."
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
