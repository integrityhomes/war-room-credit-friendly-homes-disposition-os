from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_corepilot_page_is_simple_and_read_only() -> None:
    source = (ROOT / "pages" / "49_CommandCore_Command_Bot.py").read_text(encoding="utf-8")
    assert 'render_page_header("CorePilot"' in source
    assert "What do you need?" in source
    assert "What I found" in source
    assert "Needs attention" in source
    assert "Recommended next step" in source
    assert "Advanced settings" not in source  # shared collapsed UX helper supplies the label
    assert '"action": "list"' in source
    assert '"action": "upsert"' not in source
    assert '"action": "create"' not in source
    assert "dispatch_command" not in source


def test_navigation_uses_official_user_facing_name() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"Ask CorePilot"' in app
    assert 'title="CorePilot"' in app
