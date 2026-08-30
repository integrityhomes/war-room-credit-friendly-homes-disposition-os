from pathlib import Path


def setup_status_source() -> str:
    return Path("pages/31_16_Channel_Completion_Audit.py").read_text(encoding="utf-8")


def test_marketing_setup_status_leads_with_operational_state() -> None:
    source = setup_status_source()

    for marker in (
        'st.title("CommandCore Marketing Setup Status")',
        'metric("Ready Now"',
        'metric("Not Ready Yet"',
        'st.write("### What still needs to be finished")',
    ):
        assert marker in source


def test_marketing_setup_status_routes_to_next_work() -> None:
    source = setup_status_source()

    for marker in (
        '"Open Connections"',
        'st.switch_page("pages/32_Go_Live_Connection_Center.py")',
        '"Open Marketing Home"',
        'st.switch_page("pages/90_CFH_Marketing_Dispo.py")',
    ):
        assert marker in source


def test_detailed_channel_matrix_is_secondary() -> None:
    source = setup_status_source()

    assert 'with st.expander("Complete marketing setup detail", expanded=False):' in source
    assert '"Download Marketing Setup Audit CSV"' in source
