from pathlib import Path


def source() -> str:
    return Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8")


def test_crm_starts_with_one_guided_lead_flow() -> None:
    crm = source()

    for marker in (
        'st.tabs(["Add New Lead", "Find & Edit"])',
        'st.subheader("Add New Lead")',
        'st.markdown("### 1. Seller")',
        'st.markdown("### 2. Property")',
        'st.markdown("### 3. Deal")',
        'st.form_submit_button("Create Lead & Open Deal"',
    ):
        assert marker in crm


def test_guided_lead_links_contact_property_and_deal() -> None:
    crm = source()

    assert 'contact_result = save_record("contacts", seller)' in crm
    assert 'property_result = save_record("properties", property_record)' in crm
    assert '"links": {"contact_id": contact_id, "property_id": property_id}' in crm
    assert 'st.session_state["commandcore_selected_deal_id"] = deal_id' in crm
    assert 'st.switch_page("pages/45_CommandCore_Deal_Record.py")' in crm


def test_normal_intake_uses_controlled_pipeline_choices() -> None:
    crm = source()

    assert 'PIPELINE_STAGES = [' in crm
    assert 'DEAL_STATUSES = ["Active", "On Hold", "Closed", "Dead"]' in crm
    assert 'with st.expander("More deal details (optional)")' in crm
    assert 'st.caption("Use this area when you need to correct an existing seller, property, or deal.")' in crm
