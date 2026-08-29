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


def test_current_internal_finish_backlog_is_explicit() -> None:
    backlog = {row.path for row in needs_work()}

    assert backlog == {
        "pages/14_AI_Creative_Winner_Rotation.py",
        "pages/15_AI_Buyer_Acquisition_Growth.py",
        "pages/16_AI_Buyer_Conversion_Command_Center.py",
    }


def test_external_blockers_are_not_mislabeled_as_internal_work() -> None:
    for row in APP_COMPLETION_BY_PATH.values():
        if row.state == AppCompletionState.EXTERNAL_BLOCKER:
            assert row.blocker.strip()
