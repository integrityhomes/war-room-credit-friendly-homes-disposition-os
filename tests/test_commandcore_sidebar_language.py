def read_app() -> str:
    with open("app.py", encoding="utf-8") as handle:
        return handle.read()


def test_sidebar_uses_plain_business_labels() -> None:
    source = read_app()

    for marker in (
        'title="Leads"',
        'title="Deal Workspace"',
        'title="Deal Next Steps"',
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
