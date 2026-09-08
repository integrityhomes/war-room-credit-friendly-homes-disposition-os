from pathlib import Path


def app_source() -> str:
    return Path("app.py").read_text(encoding="utf-8")


def test_daily_buyers_and_management_navigation_stays_focused() -> None:
    source = app_source()
    everyday = source[source.index("EVERYDAY_NAVIGATION"):source.index("ADMIN_ADVANCED_NAVIGATION")]

    assert 'NavigationItem("pages/90_CFH_Marketing_Dispo.py", "Marketing Home")' in everyday
    assert 'NavigationItem("pages/39_CommandCore_Operations_Hub.py", "Operations")' in everyday
    assert 'NavigationItem("pages/38_CommandCore_Management_Alerts.py", "Alerts")' in everyday
    assert 'NavigationItem("pages/40_CommandCore_Team_Health.py", "Team Health")' in everyday
    assert "pages/19_Dwelyx_Results_Attribution.py" not in everyday


def test_buyer_reporting_remains_reachable_under_advanced_tools() -> None:
    source = app_source()
    advanced = source[source.index("ADMIN_ADVANCED_NAVIGATION"):source.index("storage = get_storage()")]

    assert 'NavigationItem("pages/19_Dwelyx_Results_Attribution.py", "Buyer Results")' in advanced
    assert 'st.Page("pages/19_Dwelyx_Results_Attribution.py", title="Buyer Results")' in source
