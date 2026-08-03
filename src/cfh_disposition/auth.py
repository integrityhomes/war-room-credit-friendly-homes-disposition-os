from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any


def _render_authenticated_shortcuts() -> None:
    try:
        import streamlit as st
    except ImportError:
        return
    if st.session_state.get("authenticated"):
        st.sidebar.markdown("[🔗 14-Channel Link Center](?channel_center=1)")
        st.sidebar.markdown("[📊 14-Channel Marketing Analytics](?analytics=1)")


def configured_password(secrets: Mapping[str, Any]) -> str:
    _render_authenticated_shortcuts()
    value = secrets.get("APP_PASSWORD", "")
    return str(value).strip()


def password_matches(submitted: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))
