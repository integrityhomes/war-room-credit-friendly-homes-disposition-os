from pathlib import Path


def test_commandcore_home_prioritizes_daily_work_over_tool_catalog() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")

    assert 'st.expander("Advanced tool directory", expanded=False)' in source
    assert '"Add / Find Lead"' in source
    assert '"My Work"' in source
    assert '"Owner Approvals"' in source
    assert '"Open a Deal"' in source
    assert '"Pipeline & Follow-Up"' in source


def test_commandcore_home_uses_plain_user_facing_setup_language() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")

    assert "CommandCore sign-in is not configured yet." in source
    assert "CommandCore data connection is not configured." in source
    assert "APP_PASSWORD is added in Streamlit Secrets" not in source
    assert "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required" not in source


def test_commandcore_home_keeps_consequential_actions_gated() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")

    assert "Command Bot cannot send, sign, approve, change legal terms, move money" in source
    assert "Connecting ad accounts or spending money still requires owner authorization." in source
