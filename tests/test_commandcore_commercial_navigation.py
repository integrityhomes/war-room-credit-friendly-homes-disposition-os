from pathlib import Path


def test_commandcore_hides_automatic_page_catalog() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'st.navigation(pages, position="hidden")' in source
    assert "render_commandcore_sidebar()" in source


def test_commercial_sidebar_keeps_six_approved_areas_and_primary_destinations() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    for area in (
        'st.markdown("#### Home / Command Center")',
        'st.markdown("#### Leads & CRM")',
        'st.markdown("#### Deals")',
        'st.markdown("#### Tasks & Follow-Up")',
        'st.markdown("#### Marketing & Dispo")',
        'st.markdown("#### Management")',
    ):
        assert area in source

    for primary in (
        'sidebar_link("pages/00_CommandCore.py", "Command Center"',
        'sidebar_link("pages/44_CommandCore_CRM.py", "Leads"',
        'sidebar_link("pages/45_CommandCore_Deal_Record.py", "Deal Workspace"',
        'sidebar_link("pages/35_CommandCore_My_Work.py", "My Work"',
        'sidebar_link("pages/90_CFH_Marketing_Dispo.py", "Marketing Home"',
        'sidebar_link("pages/48_CommandCore_Owner_Approvals.py", "Owner Approvals"',
        'sidebar_link("pages/39_CommandCore_Operations_Hub.py", "Operations"',
        'sidebar_link("pages/50_CommandCore_Contract_Templates.py", "Contract Templates"',
    ):
        assert primary in source


def test_specialty_engines_remain_registered_but_off_primary_sidebar() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    for specialty in (
        'st.Page("pages/24_15_Channel_Campaign_Cadence_Refresh.py"',
        'st.Page("pages/28_Meta_Google_Paid_Traffic.py"',
        'st.Page("pages/34_Safe_Full_Payload_Test.py"',
        'st.Page("pages/43_CommandCore_CRM_Migration.py"',
    ):
        assert specialty in source

    assert 'with st.expander("Admin & setup", expanded=False):' in source
