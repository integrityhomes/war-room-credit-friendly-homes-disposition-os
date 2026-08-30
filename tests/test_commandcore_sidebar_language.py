def read_app() -> str:
    with open("app.py", encoding="utf-8") as handle:
        return handle.read()


def test_sidebar_uses_plain_business_labels() -> None:
    source = read_app()

    for marker in (
        'title="Leads"',
        'title="Deal Workspace"',
        'title="Deal Work Queue"',
        'title="Follow-Up & Pipeline"',
        'title="Marketing Home"',
        'title="Buyer Results"',
        'title="Disposition"',
        'title="Operations"',
        'title="CRM Import"',
        'title="Connections"',
    ):
        assert marker in source

    assert 'title="System Diagnostic"' not in source


def test_sidebar_keeps_the_six_approved_areas() -> None:
    source = read_app()

    for area in (
        '"Home / Command Center": [',
        '"Leads & CRM": [',
        '"Deals": [',
        '"Tasks & Follow-Up": [',
        '"Marketing & Dispo": [',
        '"Management": [',
    ):
        assert area in source

    assert '"Marketing Planning": [' not in source
    assert '"System & Setup": [' not in source


def test_contract_templates_are_admin_setup_not_daily_management_navigation() -> None:
    source = read_app()
    management_start = source.index('st.markdown("#### Management")')
    admin_start = source.index('with st.expander("Admin & setup", expanded=False):', management_start)
    templates_link = 'sidebar_link("pages/50_CommandCore_Contract_Templates.py", "Contract Templates", "📄")'

    assert templates_link not in source[management_start:admin_start]
    assert templates_link in source[admin_start:]
