"""Safe access to Streamlit secrets with env-var fallback.

Missing ``secrets.toml`` must not crash the app. Callers should use
``get_secrets()`` instead of ``st.secrets`` so demo / local boots work.
"""
from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from typing import Any


class AppSecrets(Mapping[str, Any]):
    """Read-only secrets mapping: Streamlit values first, then environment."""

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self._values = dict(values or {})

    def __getitem__(self, key: str) -> Any:
        name = str(key)
        if name in self._values:
            value = self._values[name]
            if value is not None and str(value) != "":
                return value
        if name in os.environ:
            return os.environ[name]
        if name in self._values:
            return self._values[name]
        raise KeyError(name)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        try:
            return self[key]
        except KeyError:
            return default

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"AppSecrets({sorted(self._values)!r})"

def _load_streamlit_secrets() -> dict[str, Any]:
    try:
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError
    except ImportError:
        return {}

    try:
        secrets_obj = st.secrets
        if hasattr(secrets_obj, "to_dict"):
            raw = secrets_obj.to_dict()
            return dict(raw) if isinstance(raw, Mapping) else {}
        return {str(key): secrets_obj[key] for key in secrets_obj}
    except StreamlitSecretNotFoundError:
        return {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # pragma: no cover - defensive for Streamlit variants
        message = str(exc).lower()
        name = type(exc).__name__
        if "secret" in name.lower() or "no secrets found" in message:
            return {}
        raise

def get_secrets() -> AppSecrets:
    """Return application secrets without raising when no secrets file exists.

    Prefer Streamlit Secrets when present. Fall back to environment variables
    for individual keys via ``AppSecrets.get`` / ``[]``.
    """

    return AppSecrets(_load_streamlit_secrets())

def secret_value(key: str, default: str = "") -> str:
    """Return a single secret as a stripped string."""

    value = get_secrets().get(key, default)
    return "" if value is None else str(value).strip()
