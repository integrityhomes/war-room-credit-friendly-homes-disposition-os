def test_agent_finder_is_embedded_in_contacts_not_a_separate_crm_flow() -> None:
    with open("pages/44_CommandCore_CRM.py", encoding="utf-8") as source_file:
        source = source_file.read()

    assert "from cfh_disposition.commandcore_agent_finder_ui import render_agent_finder" in source
    assert 'if entity == "contacts":' in source
    assert "render_agent_finder(" in source
    assert 'deals=load_records("deals")' in source
    assert 'properties=load_records("properties")' in source
    assert "saved = contact_form(selected)" in source
    assert "saved = property_form(selected)" in source
    assert "saved = deal_form(selected" in source
