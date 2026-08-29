from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages/48_CommandCore_Owner_Approvals.py"


def _source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_owner_decision_history_uses_stable_identity_not_timestamp():
    source = _source()
    assert 'history_external_id = f"owner-decision-{entity}-{record_id}"' in source
    assert 'f"owner-decision-{entity}-{record_id}-{timestamp}"' not in source
    assert '"owner_decision_history_external_id": history_external_id' in source
    assert '"owner_decision_history_recorded": True' in source


def test_owner_decision_history_is_written_before_terminal_approval_state():
    source = _source()
    history_write = source.index('upsert(\n        "activities",')
    record_write = source.index("upsert(entity, updated)")
    assert history_write < record_write


def test_owner_approval_safety_boundaries_remain_in_place():
    source = _source()
    assert 'st.secrets.get("OWNER_APPROVAL_PIN", "")' in source
    assert "if owner_name not in OWNER_NAMES:" in source
    assert "elif not confirm:" in source
    assert "elif not verify_owner_pin(pin):" in source
    assert '"external_action_started": False' in source
    assert "It does not send the offer or bind the company." in source
    assert "does not sign, send, or externally execute anything" in source
