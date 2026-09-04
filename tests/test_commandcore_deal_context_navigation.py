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
    assert 'selected_label = st.selectbox("Open deal"' in source
    assert 'label="← Command Center"' not in source
    assert 'label="Pipeline & Follow-Up"' not in source


def test_deal_marketing_handoff_passes_property_context_safely() -> None:
    deal_source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")
    marketing_source = Path("pages/90_CFH_Marketing_Dispo.py").read_text(encoding="utf-8")

    assert 'st.session_state["commandcore_marketing_property_id"] = property_id' in deal_source
    assert 'st.session_state["commandcore_marketing_property_address"] = address' in deal_source
    assert 'st.session_state["pending_main_navigation"] = "Marketing Home"' in deal_source
    assert 'st.switch_page("pages/90_CFH_Marketing_Dispo.py")' in deal_source

    assert 'st.session_state.pop("commandcore_marketing_property_id", "")' in marketing_source
    assert 'st.session_state.pop("commandcore_marketing_property_address", "")' in marketing_source
    assert "if requested_label:" in marketing_source
    assert "This Deal's linked property is not available in Marketing yet." in marketing_source
