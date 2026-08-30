from pathlib import Path


def management_alerts_source() -> str:
    return Path("pages/38_CommandCore_Management_Alerts.py").read_text(encoding="utf-8")


def test_management_alerts_use_business_first_columns() -> None:
    source = management_alerts_source()

    for marker in (
        '"Urgency":',
        '"Owner":',
        '"Problem":',
        '"Do This Next":',
        'st.subheader("Handle These First")',
    ):
        assert marker in source

    priority_queue_start = source.index('st.subheader("Management Priority Queue")')
    handle_first_start = source.index('st.subheader("Handle These First")')
    priority_queue = source[priority_queue_start:handle_first_start]
    assert '"Dispatch":' not in priority_queue


def test_management_alerts_open_exact_resolution_workspace() -> None:
    source = management_alerts_source()

    assert '"Open Coverage Exceptions"' in source
    assert 'st.switch_page("pages/37_CommandCore_Coverage_Exceptions.py")' in source
    assert 'with st.expander("Technical details", expanded=False):' in source


def test_empty_management_alert_queue_has_safe_next_actions() -> None:
    source = management_alerts_source()

    for marker in (
        'st.markdown("### Management alert queue is clear")',
        '"Open Operations"',
        'st.switch_page("pages/39_CommandCore_Operations_Hub.py")',
        '"Review Owner Approvals"',
        'st.switch_page("pages/48_CommandCore_Owner_Approvals.py")',
    ):
        assert marker in source
