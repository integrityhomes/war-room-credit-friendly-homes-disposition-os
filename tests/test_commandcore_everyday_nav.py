from pathlib import Path


def test_everyday_sidebar_is_core_areas_only() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    everyday = source.split("EVERYDAY_NAVIGATION = (", 1)[1].split("ADMIN_ADVANCED_NAVIGATION = (", 1)[0]
    for label in (
        '"Leads / CRM"',
        '"Deals"',
        '"Approvals"',
        '"Marketing"',
        '"Buyers"',
        '"Admin"',
    ):
        assert label in everyday
    # Specialty tools stay out of everyday nav.
    assert "Facebook Groups" not in everyday
    assert "Ask CorePilot" not in everyday
    assert "Property Terms Testing" not in everyday
    advanced = source.split("ADMIN_ADVANCED_NAVIGATION = (", 1)[1].split("storage = get_storage()", 1)[0]
    assert "Ask CorePilot" in advanced
    assert "Facebook Groups" in advanced


def test_duplicate_page_numbers_were_renamed() -> None:
    pages = {path.name for path in Path("pages").glob("*.py")}
    # Exactly one page per former duplicate number.
    assert sum(1 for name in pages if name.startswith("21_")) == 1
    assert sum(1 for name in pages if name.startswith("49_")) == 1
    assert "21_Property_Terms_Test_Relaunch.py" in pages
    assert "49_CommandCore_Command_Bot.py" in pages
    assert "21_CommandCore_Operator_Dashboard.py" not in pages
    assert "49_CommandCore_Phone_System_Setup.py" not in pages
    assert "56_CommandCore_Operator_Dashboard.py" in pages
    assert "57_CommandCore_Phone_System_Setup.py" in pages
