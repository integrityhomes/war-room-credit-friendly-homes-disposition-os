from pathlib import Path


def marketing_source() -> str:
    return Path("pages/90_CFH_Marketing_Dispo.py").read_text(encoding="utf-8")


def test_marketing_home_is_the_primary_commandcore_experience() -> None:
    source = marketing_source()

    for marker in (
        'page_title="CommandCore Marketing & Dispo"',
        'st.title("CommandCore Marketing & Dispo")',
        'st.subheader("Marketing Home")',
        '"Property → Prepare Campaign → Launch Marketing.',
        '"Marketing Home":',
    ):
        assert marker in source


def test_marketing_workflow_navigation_is_secondary_not_sidebar_clutter() -> None:
    source = marketing_source()

    assert 'with st.expander("Jump to a marketing step or advanced tool", expanded=False):' in source
    assert 'page = st.selectbox(' in source
    assert 'st.sidebar.radio(' not in source
    assert 'st.sidebar.success(f"Storage:' not in source
    assert 'st.sidebar.button("Refresh saved records")' not in source


def test_advanced_and_system_tools_remain_available() -> None:
    source = marketing_source()

    for marker in (
        '"More Tools": "Advanced Tools"',
        '"System Setup": "System Setup"',
        'st.subheader("Advanced Marketing Tools")',
        'st.subheader("System Setup")',
        'st.button("Refresh Saved Records")',
        'render_record_manager(storage)',
        'render_marketplace_guard(st.session_state.properties, st.secrets)',
    ):
        assert marker in source


def test_dwelyx_postponement_does_not_block_marketing_flow() -> None:
    source = marketing_source()

    assert "Dwelyx live connection is postponed" in source
    assert "does not block CommandCore marketing setup" in source
