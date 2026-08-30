from __future__ import annotations

import streamlit as st

from cfh_disposition.auth import configured_password, password_matches
from cfh_disposition.dwelyx import dwelyx_base_url
from cfh_disposition.facebook_groups_ui import render_facebook_group_posting_center
from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import StorageError, build_storage

st.set_page_config(
    page_title="Facebook Group Posting Center",
    page_icon="👥",
    layout="wide",
)


def require_password() -> None:
    expected = configured_password(st.secrets)
    if not expected:
        st.error("This app is locked until APP_PASSWORD is added in Streamlit Secrets.")
        st.stop()
    if st.session_state.get("authenticated"):
        return

    st.title("Facebook Group Posting Center")
    st.caption("Private internal access")
    with st.form("facebook_group_login"):
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
st.title("Facebook Group Posting Center")
st.caption(
    "Use tracked Dwelyx links in Facebook Groups while preventing accidental duplicate posts."
)

try:
    storage = get_storage()
    properties = storage.list_properties()
except StorageError as exc:
    st.error(f"Properties could not be loaded: {exc}")
    st.stop()

render_facebook_group_posting_center(
    properties,
    st.secrets,
    dwelyx_base_url(st.secrets),
)

with st.expander("Facebook setup & supporting tools", expanded=False):
    st.caption("Use these only when you need to maintain the group list, prepare copy variations, or review team assignments.")
    import_col, variation_col, assignments_col = st.columns(3)
    with import_col:
        st.page_link(
            "pages/8_Facebook_Group_Bulk_Import.py",
            label="Add / Import Groups",
            icon="📥",
            use_container_width=True,
        )
    with variation_col:
        st.page_link(
            "pages/9_Facebook_Group_Variation_Pack.py",
            label="Create Variation Pack",
            icon="📝",
            use_container_width=True,
        )
    with assignments_col:
        st.page_link(
            "pages/10_Facebook_Daily_Assignments.py",
            label="Daily Assignments",
            icon="📋",
            use_container_width=True,
        )
