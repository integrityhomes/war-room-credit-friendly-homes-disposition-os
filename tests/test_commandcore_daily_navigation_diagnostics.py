from pathlib import Path


APP = Path("app.py")
DIAGNOSTIC = Path("pages/34_Safe_Full_Payload_Test.py")


def test_system_diagnostic_remains_available_in_repo_but_out_of_daily_navigation() -> None:
    source = APP.read_text(encoding="utf-8")

    assert DIAGNOSTIC.exists()
    assert "pages/34_Safe_Full_Payload_Test.py" not in source
    assert "System Diagnostic" not in source


def test_six_approved_commandcore_areas_remain_in_shell() -> None:
    source = APP.read_text(encoding="utf-8")
    for area in (
        "Home / Command Center",
        "Leads & CRM",
        "Deals",
        "Tasks & Follow-Up",
        "Marketing & Dispo",
        "Management",
    ):
        assert f'"{area}": [' in source
