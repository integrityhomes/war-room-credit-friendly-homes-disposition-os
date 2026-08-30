from pathlib import Path


def source() -> str:
    return Path("pages/47_CommandCore_Deal_Workflow_Queue.py").read_text(encoding="utf-8")


def test_deal_work_queue_uses_business_language() -> None:
    page = source()

    for marker in (
        'st.title("CommandCore Deal Work Queue")',
        'metrics[0].metric("Open Work"',
        'metrics[1].metric("Ready to Work"',
        'metrics[2].metric("Needs Information"',
        'metrics[3].metric("Needs Owner"',
        '"Work type"',
    ):
        assert marker in page


def test_deal_work_queue_opens_exact_deal() -> None:
    page = source()

    assert 'st.session_state["commandcore_selected_deal_id"] = deal_id' in page
    assert 'st.switch_page("pages/45_CommandCore_Deal_Record.py")' in page
    assert 'st.button("Open Deal"' in page


def test_technical_coordination_details_are_secondary() -> None:
    page = source()

    assert 'with st.expander("More details", expanded=False):' in page
    assert '**Coordination:**' in page
    assert 'Task ID:' in page


def test_empty_deal_work_queue_has_clear_next_actions() -> None:
    page = source()

    for marker in (
        'st.markdown("### No deal work is waiting")',
        '"Open Deal Workspace"',
        'st.switch_page("pages/45_CommandCore_Deal_Record.py")',
        '"Add New Lead"',
        'st.switch_page("pages/44_CommandCore_CRM.py")',
    ):
        assert marker in page
