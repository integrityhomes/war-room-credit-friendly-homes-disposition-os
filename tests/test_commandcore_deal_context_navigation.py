from pathlib import Path


def test_crm_selected_deal_opens_unified_deal_record() -> None:
    source = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    assert '"Open Unified Deal Record"' in source
    assert 'st.session_state["commandcore_selected_deal_id"]' in source
    assert 'st.switch_page("pages/45_CommandCore_Deal_Record.py")' in source


def test_deal_record_honors_and_remembers_selected_deal_context() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")

    assert 'st.session_state.get("commandcore_selected_deal_id")' in source
    assert 'st.session_state["commandcore_selected_deal_id"] = deal_id' in source
    assert 'st.page_link("pages/44_CommandCore_CRM.py", label="← Back to Leads & CRM")' in source
