from pathlib import Path

from cfh_disposition.app_completion import APP_COMPLETION_BY_PATH, AppCompletionState, needs_work


def test_every_streamlit_page_is_classified_exactly_once() -> None:
    actual = {path.as_posix() for path in Path("pages").glob("*.py")}
    classified = set(APP_COMPLETION_BY_PATH)

    assert classified == actual, (
        f"Unclassified pages: {sorted(actual - classified)}; "
        f"stale ledger entries: {sorted(classified - actual)}"
    )


def test_completion_ledger_has_no_duplicate_paths() -> None:
    assert len(APP_COMPLETION_BY_PATH) == len(set(APP_COMPLETION_BY_PATH))


def test_current_internal_finish_backlog_is_empty() -> None:
    assert needs_work() == ()


def test_external_blockers_are_not_mislabeled_as_internal_work() -> None:
    for row in APP_COMPLETION_BY_PATH.values():
        if row.state == AppCompletionState.EXTERNAL_BLOCKER:
            assert row.blocker.strip()


def test_operator_dashboard_is_a_completed_my_work_compatibility_route() -> None:
    row = APP_COMPLETION_BY_PATH["pages/21_CommandCore_Operator_Dashboard.py"]

    assert row.state == AppCompletionState.COMPLETE
    assert "My Work" in row.disposition
    assert "compatibility" in row.disposition.lower()


def test_record_manager_is_a_completed_marketing_home_compatibility_surface() -> None:
    row = APP_COMPLETION_BY_PATH["pages/01_Record_Manager.py"]

    assert row.state == AppCompletionState.COMPLETE
    assert "Marketing Home" in row.disposition
    assert "Record Manager" in row.disposition
    assert "compatibility" in row.disposition.lower()
