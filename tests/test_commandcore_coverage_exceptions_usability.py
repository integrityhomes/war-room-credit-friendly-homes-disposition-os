from pathlib import Path


def coverage_source() -> str:
    return Path("pages/37_CommandCore_Coverage_Exceptions.py").read_text(encoding="utf-8")


def test_coverage_exceptions_put_problem_and_action_first() -> None:
    source = coverage_source()

    assert 'st.write(f"**What failed:** {reason}")' in source
    assert 'st.write(f"**What management should do:** {management_action(item)}")' in source
    assert 'with st.expander("Technical details", expanded=False):' in source

    business_action = source.index('st.write(f"**What management should do:** {management_action(item)}")')
    technical_details = source.index('with st.expander("Technical details", expanded=False):')
    assert business_action < technical_details


def test_coverage_exceptions_keep_status_controls() -> None:
    source = coverage_source()

    for marker in (
        'b1.form_submit_button("Acknowledge")',
        'b2.form_submit_button("Mark Resolved", type="primary")',
        'b3.form_submit_button("Reopen")',
        'update_status(exception_id, requested_status, actor, note)',
    ):
        assert marker in source


def test_empty_coverage_view_has_safe_next_actions() -> None:
    source = coverage_source()

    for marker in (
        '"Open Operations"',
        'st.switch_page("pages/39_CommandCore_Operations_Hub.py")',
        '"Review Management Alerts"',
        'st.switch_page("pages/38_CommandCore_Management_Alerts.py")',
    ):
        assert marker in source
