from __future__ import annotations

from typing import Any

import pytest

from cfh_disposition import app_secrets as app_secrets_module
from cfh_disposition.app_secrets import AppSecrets, get_secrets, secret_value


def test_app_secrets_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", " from-env ")
    secrets = AppSecrets({})
    assert secrets.get("APP_PASSWORD") == " from-env "
    assert secrets.get("MISSING", "default") == "default"


def test_app_secrets_prefers_non_empty_mapping_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "env-value")
    secrets = AppSecrets({"APP_PASSWORD": "mapped-value"})
    assert secrets["APP_PASSWORD"] == "mapped-value"
    assert secrets.get("APP_PASSWORD") == "mapped-value"


def test_app_secrets_empty_mapping_value_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "env-only")
    secrets = AppSecrets({"APP_PASSWORD": ""})
    assert secrets.get("APP_PASSWORD") == "env-only"


def test_get_secrets_survives_missing_streamlit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_secrets_module, "_load_streamlit_secrets", lambda: {})
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    secrets = get_secrets()
    assert secrets.get("SUPABASE_URL") == "https://example.supabase.co"
    assert secret_value("SUPABASE_URL") == "https://example.supabase.co"
    assert secret_value("MISSING_KEY") == ""


def test_load_streamlit_secrets_swallows_missing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.errors import StreamlitSecretNotFoundError

    class FakeSecrets:
        def to_dict(self) -> dict[str, Any]:
            raise StreamlitSecretNotFoundError("No secrets found")

    class FakeSt:
        secrets = FakeSecrets()

    monkeypatch.setitem(__import__("sys").modules, "streamlit", FakeSt())
    # Force re-import path through _load_streamlit_secrets which imports streamlit
    # Replace st inside the function by patching import target after load
    def fake_load() -> dict[str, Any]:
        try:
            raise StreamlitSecretNotFoundError("No secrets found")
        except StreamlitSecretNotFoundError:
            return {}

    monkeypatch.setattr(app_secrets_module, "_load_streamlit_secrets", fake_load)
    assert get_secrets().get("APP_PASSWORD", "") == ""
