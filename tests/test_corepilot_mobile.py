from pathlib import Path

PAGE = Path("pages/49_CommandCore_Command_Bot.py").read_text(encoding="utf-8")


def test_same_corepilot_page_serves_desktop_and_phone() -> None:
    assert "render_mobile_styles()" in PAGE
    assert "createBrowserTab" not in PAGE
    assert "native app" not in PAGE.casefold()
    assert PAGE.count("run_corepilot(") == 1


def test_common_phone_widths_use_one_column_without_horizontal_scroll() -> None:
    assert "@media (max-width: 640px)" in PAGE
    assert "flex-direction: column" in PAGE
    assert "width: 100% !important" in PAGE
    assert "overflow-x: hidden" in PAGE
    assert "overflow-wrap: anywhere" in PAGE


def test_phone_controls_have_touch_friendly_minimum_height_and_quick_actions() -> None:
    assert "min-height: 44px" in PAGE
    for label in ("What needs my attention?", "Find a deal", "Show my work", "Review communications"):
        assert label in PAGE


def test_mobile_uses_existing_authentication_and_safety_boundaries() -> None:
    assert "configured_password(st.secrets)" in PAGE
    assert "password_matches(password, expected)" in PAGE
    assert "CorePilot stopped before the protected action" in PAGE
    assert "CorePilotActionClass.APPROVAL_REQUIRED" in PAGE
    assert '"action": "list"' in PAGE
    assert '"action": "upsert"' not in PAGE
