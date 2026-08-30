from pathlib import Path


def team_health_source() -> str:
    return Path("pages/40_CommandCore_Team_Health.py").read_text(encoding="utf-8")


def test_team_health_routes_management_to_resolution_work() -> None:
    source = team_health_source()

    for marker in (
        '"Review Workload"',
        'st.switch_page("pages/41_CommandCore_Workload_Balance.py")',
        '"Resolve Coverage Problems"',
        'st.switch_page("pages/37_CommandCore_Coverage_Exceptions.py")',
    ):
        assert marker in source


def test_healthy_team_state_has_safe_next_actions() -> None:
    source = team_health_source()

    for marker in (
        '"Open Operations"',
        'st.switch_page("pages/39_CommandCore_Operations_Hub.py")',
        '"Review My Work"',
        'st.switch_page("pages/35_CommandCore_My_Work.py")',
    ):
        assert marker in source


def test_empty_team_health_view_explains_why_it_is_empty() -> None:
    source = team_health_source()

    assert 'st.markdown("### No team members are registered yet")' in source
    assert "Team workload health will populate after the CommandCore team registry has active members." in source
