from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any

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
