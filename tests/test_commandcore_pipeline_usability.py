from pathlib import Path


def test_pipeline_starts_with_followup_today_and_shows_upcoming_work() -> None:
    source = Path("pages/46_CommandCore_Pipeline_Followup.py").read_text(encoding="utf-8")

    for marker in (
        'followup_tab, pipeline_tab = st.tabs(["Follow-Up Today", "Pipeline"])',
        'st.subheader("Needs attention now")',
        'st.subheader("Coming up next")',
        'for task in upcoming[:20]:',
        'show_followup_task(task, deals, key_prefix="followup_upcoming")',
    ):
        assert marker in source


def test_pipeline_uses_sidebar_instead_of_duplicate_top_navigation() -> None:
    source = Path("pages/46_CommandCore_Pipeline_Followup.py").read_text(encoding="utf-8")

    assert 'label="← Command Center"' not in source
    assert 'label="My Work"' not in source
    assert 'label="Unified Deal Record"' not in source
