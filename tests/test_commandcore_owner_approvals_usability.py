from pathlib import Path


def test_owner_approvals_puts_decisions_before_blockers() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    for marker in (
        'decision_tab, blocked_tab = st.tabs(["Needs My Decision", "Blocked / Needs Setup"])',
        'm1.metric("Needs my decision"',
        'with st.expander("Advanced details", expanded=False)',
        'label: str = "Review"',
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


def test_each_approval_explains_context_risk_and_outcomes() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    for marker in (
        '"**Requested by:**',
        '"**Related to:**',
        '"**Risk:**',
        '"**Why approval is needed:**',
        'return "Normal"',
        'return "Needs attention"',
        'return "High risk"',
        '"Send back for changes"',
        '"Approve"',
        '"Reject"',
    ):
        assert marker in source


def test_action_results_explain_what_happened_and_what_comes_next() -> None:
    source = Path("pages/48_CommandCore_Owner_Approvals.py").read_text(encoding="utf-8")

    assert source.count("queue_success(") == 2
    assert "show_queued_success()" in source
    assert "No external action was started." in source
    assert "The internal workflow can continue" in source
    assert "submitted for approval again" in source
