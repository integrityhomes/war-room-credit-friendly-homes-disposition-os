from pathlib import Path


def test_owner_approvals_puts_decisions_before_blockers() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    for marker in (
        'decision_tab, blocked_tab = st.tabs(["Needs My Decision", "Blocked / Needs Setup"])',
        'm1.metric("Needs my decision"',
        'with st.expander("Review supporting details")',
        '"Open Unified Deal Record"',
    ):
        assert marker in source


def test_owner_approvals_keeps_owner_pin_and_confirmation_controls() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    assert 'st.secrets.get("OWNER_APPROVAL_PIN"' in source
    assert '"Decision maker"' in source
    assert '"Owner approval PIN"' in source
    assert '"I understand this records an owner decision and I am the owner named above."' in source
