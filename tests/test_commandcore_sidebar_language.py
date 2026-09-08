from pathlib import Path


def read_app() -> str:
    return Path("app.py").read_text(encoding="utf-8")


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


def test_sidebar_keeps_the_existing_registered_areas() -> None:
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


def test_administrator_tools_are_not_in_everyday_navigation() -> None:
    source = read_app()
    everyday = source.split("EVERYDAY_NAVIGATION =", 1)[1].split(
        "ADMIN_ADVANCED_NAVIGATION =", 1
    )[0]
    advanced = source.split("ADMIN_ADVANCED_NAVIGATION =", 1)[1].split(
        "storage = get_storage()", 1
    )[0]

    assert 'NavigationItem("pages/48_CommandCore_Owner_Approvals.py", "Owner Approvals")' in everyday
    assert 'NavigationItem("pages/39_CommandCore_Operations_Hub.py", "Operations")' in everyday
    for label in ("Contract Templates", "CRM Import", "Connections", "Internal Connection Check"):
        assert label not in everyday
        assert label in advanced


def test_specialty_marketing_tools_are_grouped_under_advanced_tools() -> None:
    source = read_app()
    everyday = source.split("EVERYDAY_NAVIGATION =", 1)[1].split(
        "ADMIN_ADVANCED_NAVIGATION =", 1
    )[0]
    advanced = source.split("ADMIN_ADVANCED_NAVIGATION =", 1)[1].split(
        "storage = get_storage()", 1
    )[0]

    assert 'NavigationItem("pages/90_CFH_Marketing_Dispo.py", "Marketing Home")' in everyday
    for marker in (
        'NavigationItem("pages/7_Facebook_Group_Posting_Center.py", "Facebook Groups")',
        'NavigationItem("pages/25_Property_Channel_Tracking_Links.py", "Tracking Links")',
        'NavigationItem("pages/23_Daily_Executive_Disposition_Command.py", "Disposition Performance")',
    ):
        assert marker in advanced
