from pathlib import Path


def test_command_center_hides_secondary_workspace_browser_by_default() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")

    assert 'with st.expander("Advanced tool directory", expanded=False):' in source
    assert 'area = st.selectbox(' in source
    assert 'st.segmented_control(' not in source


def test_command_center_keeps_today_and_start_work_primary() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")
    home = source.split('if area == "Home / Command Center":', 1)[1].split('elif area == "Leads & CRM":', 1)[0]

    assert 'st.subheader("Today")' in home
    assert 'st.markdown("### Start work")' in home
    assert '"pages/44_CommandCore_CRM.py"' in home
    assert '"pages/35_CommandCore_My_Work.py"' in home
    assert '"pages/48_CommandCore_Owner_Approvals.py"' in home
    assert '"pages/45_CommandCore_Deal_Record.py"' in home
    assert '"pages/46_CommandCore_Pipeline_Followup.py"' in home
