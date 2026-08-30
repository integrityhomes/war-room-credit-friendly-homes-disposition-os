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


def test_empty_owner_approval_queue_gives_safe_next_actions() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    for marker in (
        'st.markdown("### You\'re clear — no owner decisions are waiting")',
        '"Open Deal Workspace"',
        'st.switch_page("pages/45_CommandCore_Deal_Record.py")',
        '"Review My Work"',
        'st.switch_page("pages/35_CommandCore_My_Work.py")',
        'CommandCore will surface new owner-gated decisions here automatically',
    ):
        assert marker in source


def test_owner_approvals_uses_sidebar_instead_of_duplicate_top_navigation() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    assert 'label="← Command Center"' not in source
    assert 'label="Unified Deal Record"' not in source
