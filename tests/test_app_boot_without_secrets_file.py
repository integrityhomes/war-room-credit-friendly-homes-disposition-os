from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"


@pytest.mark.skipif(not APP.exists(), reason="app.py missing")
def test_app_boots_when_secrets_toml_is_absent() -> None:
    """AppTest must not raise StreamlitSecretNotFoundError with no secrets.toml."""
    from streamlit.testing.v1 import AppTest

    backup = None
    if SECRETS_PATH.exists():
        backup = SECRETS_PATH.read_bytes()
        SECRETS_PATH.unlink()
    try:
        at = AppTest.from_file(str(APP), default_timeout=20)
        at.run()
        assert not at.exception, at.exception
        error_text = " ".join(str(err.value) for err in at.error).lower()
        assert "sign-in is not configured" in error_text or "not configured" in error_text
    finally:
        if backup is not None:
            SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SECRETS_PATH.write_bytes(backup)
