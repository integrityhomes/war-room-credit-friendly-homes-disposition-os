from pathlib import Path


def connections_source() -> str:
    return Path("pages/32_Go_Live_Connection_Center.py").read_text(encoding="utf-8")


def test_connections_lead_with_missing_setup() -> None:
    source = connections_source()

    for marker in (
        'st.title("CommandCore Connections")',
        'st.write("### Finish These Next")',
        'row.next_step',
        'row.required_for',
    ):
        assert marker in source


def test_connections_route_back_to_marketing_work() -> None:
    source = connections_source()

    for marker in (
        '"Open Marketing Setup Status"',
        'st.switch_page("pages/31_16_Channel_Completion_Audit.py")',
        '"Open Marketing Home"',
        'st.switch_page("pages/90_CFH_Marketing_Dispo.py")',
    ):
        assert marker in source


def test_connection_matrix_and_webhook_test_are_secondary() -> None:
    source = connections_source()

    assert 'with st.expander("All connection and setup details", expanded=False):' in source
    assert 'with st.expander("Advanced: general automation webhook", expanded=False):' in source
    assert '"Send Safe General-Webhook Test"' in source
