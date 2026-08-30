from pathlib import Path


def test_deals_workspace_prioritizes_unified_deal_record() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")
    deals = source.split('elif area == "Deals":', 1)[1].split('elif area == "Tasks & Follow-Up":', 1)[0]

    assert 'st.markdown("### Start here")' in deals
    assert deals.index('"pages/45_CommandCore_Deal_Record.py"') < deals.index('"pages/46_CommandCore_Pipeline_Followup.py"')
    assert 'st.markdown("### Supporting deal views")' in deals


def test_tasks_workspace_prioritizes_my_work() -> None:
    source = Path("pages/00_CommandCore.py").read_text(encoding="utf-8")
    tasks = source.split('elif area == "Tasks & Follow-Up":', 1)[1].split('elif area == "Marketing & Dispo":', 1)[0]

    assert 'st.markdown("### Start here")' in tasks
    assert tasks.index('"pages/35_CommandCore_My_Work.py"') < tasks.index('"pages/46_CommandCore_Pipeline_Followup.py"')
    assert 'st.markdown("### Supporting work views")' in tasks
