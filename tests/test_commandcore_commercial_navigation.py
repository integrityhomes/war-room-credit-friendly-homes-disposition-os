from pathlib import Path


def test_commandcore_hides_automatic_page_catalog() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'st.navigation(pages, position="hidden")' in source
    assert "render_sidebar_navigation(EVERYDAY_NAVIGATION, ADMIN_ADVANCED_NAVIGATION)" in source


def test_commercial_sidebar_prioritizes_everyday_work_areas() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    everyday = source.split("EVERYDAY_NAVIGATION =", 1)[1].split(
        "ADMIN_ADVANCED_NAVIGATION =", 1
    )[0]

    for area in (
        '"Home"',
        '"Leads / Sellers"',
        '"Deals / Properties"',
        '"My Work"',
        '"Buyers / Marketing"',
        '"Management"',
        '"Owner Approvals"',
    ):
        assert area in everyday

    for primary in (
        'NavigationItem("pages/00_CommandCore.py", "Home")',
        'NavigationItem("pages/44_CommandCore_CRM.py", "Leads")',
        'NavigationItem("pages/45_CommandCore_Deal_Record.py", "Deal Workspace")',
        'NavigationItem("pages/35_CommandCore_My_Work.py", "My Work")',
        'NavigationItem("pages/90_CFH_Marketing_Dispo.py", "Marketing Home")',
        'NavigationItem("pages/48_CommandCore_Owner_Approvals.py", "Owner Approvals")',
        'NavigationItem("pages/39_CommandCore_Operations_Hub.py", "Operations")',
    ):
        assert primary in everyday

    ux_source = Path("src/cfh_disposition/commandcore_ux.py").read_text(encoding="utf-8")
    assert 'with st.expander("Admin / Advanced Tools", expanded=False):' in ux_source


def test_specialty_engines_remain_registered() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    for specialty in (
        'st.Page("pages/24_15_Channel_Campaign_Cadence_Refresh.py"',
        'st.Page("pages/28_Meta_Google_Paid_Traffic.py"',
        'st.Page("pages/43_CommandCore_CRM_Migration.py"',
    ):
        assert specialty in source

    assert 'st.Page(DIAGNOSTIC_PAGE, title="Internal Check")' in source
