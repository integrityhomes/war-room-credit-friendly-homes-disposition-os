from pathlib import Path


def test_crm_deal_form_links_seller_and_property() -> None:
    source = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    for marker in (
        '"Seller / contact"',
        '"Property"',
        'updated_links["contact_id"] = contact_id',
        'updated_links["property_id"] = property_id',
        '"links": updated_links',
        'deal_form(selected, load_records("contacts"), load_records("properties"))',
    ):
        assert marker in source


def test_crm_guided_lead_flow_is_the_primary_daily_path() -> None:
    source = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    for marker in (
        'st.title("Leads & CRM")',
        'st.tabs(["Add New Lead", "Find & Edit"])',
        'st.subheader("Add New Lead")',
        'with st.form("commandcore_guided_lead_intake")',
        'st.form_submit_button("Create Lead & Open Deal"',
        '"links": {"contact_id": contact_id, "property_id": property_id}',
        'st.session_state["commandcore_selected_deal_id"] = deal_id',
        'st.switch_page("pages/45_CommandCore_Deal_Record.py")',
        '"Open Unified Deal Record"',
    ):
        assert marker in source


def test_crm_does_not_restore_duplicate_top_navigation() -> None:
    source = Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")

    assert 'label="← Command Center"' not in source
    assert 'label="Pipeline & Follow-Up"' not in source
