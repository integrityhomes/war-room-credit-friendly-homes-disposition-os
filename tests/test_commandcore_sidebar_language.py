from pathlib import Path


def test_sidebar_uses_plain_business_labels() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

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
        'title="System Diagnostic"',
    ):
        assert marker in source


def test_sidebar_keeps_the_six_approved_areas() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

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
