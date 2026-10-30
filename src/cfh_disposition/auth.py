from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any

from .app_secrets import get_secrets
from .channels import CHANNELS


def _configure_private_navigation() -> None:
    """Hide private page names until login, then show authenticated shortcuts."""
    try:
        import streamlit as st
    except ImportError:
        return

    if not st.session_state.get("authenticated"):
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        return

    channel_count = len(CHANNELS)
    st.sidebar.markdown(f"[🔗 {channel_count}-Channel Link Center](?channel_center=1)")
    st.sidebar.markdown(
        f"[📊 {channel_count}-Channel Marketing Analytics](?analytics=1)"
    )


def configured_password(secrets: Mapping[str, Any]) -> str:
    _configure_private_navigation()
    value = secrets.get("APP_PASSWORD", "")
    return str(value).strip()


def password_matches(submitted: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))


def require_password(
    *,
    title: str = "CommandCore",
    form_key: str = "commandcore_shared_login",
    unconfigured_message: str = "CommandCore sign-in is not configured yet.",
) -> None:
    """Gate private Streamlit pages behind APP_PASSWORD.

    Empty / missing APP_PASSWORD refuses access (no demo login bypass).
    Public routes must call this only after they have already returned.
    """
    import streamlit as st

    expected = configured_password(get_secrets())
    if not expected:
        st.error(unconfigured_message)
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.title(title)
    with st.form(form_key):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted and password_matches(password, expected):
        st.session_state.authenticated = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    st.stop()
