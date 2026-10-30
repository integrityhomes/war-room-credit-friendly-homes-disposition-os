from __future__ import annotations

from pathlib import Path

from cfh_disposition.auth import configured_password, password_matches, require_password

PAGES = Path("pages")


def test_no_page_defines_local_require_password() -> None:
    offenders = [
        path.name
        for path in sorted(PAGES.glob("*.py"))
        if "def require_password" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_all_private_pages_call_shared_require_password() -> None:
    missing = []
    for path in sorted(PAGES.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "from cfh_disposition.auth import require_password" not in source:
            missing.append(path.name)
            continue
        if "require_password(" not in source:
            missing.append(path.name)
    assert missing == []


def test_operator_dashboard_redirect_is_password_gated() -> None:
    source = Path("pages/56_CommandCore_Operator_Dashboard.py").read_text(encoding="utf-8")
    assert "require_password(" in source
    assert source.index("require_password(") < source.index("st.switch_page")


def test_require_password_exported_from_auth() -> None:
    assert callable(require_password)
    assert configured_password({"APP_PASSWORD": " x "}) == "x"
    assert password_matches("x", "x")
