from pathlib import Path


PAGE = Path("pages/49_CommandCore_Command_Bot.py")


def test_command_bot_uses_stable_request_identity_and_reuses_existing_work() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "def normalized_command" in source
    assert "hashlib.sha256" in source
    assert '"external_id": request_external_id' in source
    assert '"external_id": f"{request_external_id}-activity"' in source
    assert 'if text(existing.get("external_id")) == request_external_id:' in source
    assert "return existing, False" in source
    assert '"external_action_started": False' in source
    assert '"approval_bypassed": False' in source


def test_command_bot_ui_explains_duplicate_reuse() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "CommandCore reused the existing internal work" in source
    assert "instead of creating a duplicate" in source
