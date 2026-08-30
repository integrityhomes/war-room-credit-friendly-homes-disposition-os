APP = "app.py"
DIAGNOSTIC = "pages/34_Safe_Full_Payload_Test.py"


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_system_diagnostic_remains_available_in_repo_but_out_of_daily_navigation() -> None:
    source = read_text(APP)
    diagnostic_source = read_text(DIAGNOSTIC)

    assert diagnostic_source
    assert "pages/34_Safe_Full_Payload_Test.py" not in source
    assert "System Diagnostic" not in source


def test_six_approved_commandcore_areas_remain_in_shell() -> None:
    source = read_text(APP)
    for area in (
        "Home / Command Center",
        "Leads & CRM",
        "Deals",
        "Tasks & Follow-Up",
        "Marketing & Dispo",
        "Management",
    ):
        assert f'"{area}": [' in source
