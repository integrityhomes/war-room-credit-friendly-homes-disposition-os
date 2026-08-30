from pathlib import Path


def test_my_work_prioritizes_daily_actions_over_routing_details() -> None:
    source = Path("pages/35_CommandCore_My_Work.py").read_text(encoding="utf-8")

    for marker in (
        'selected_owner = st.selectbox("Show work for"',
        'st.subheader("What needs attention")',
        'st.subheader("Work Details")',
        'st.write("**What needs to happen next:**")',
        'st.toggle("Show routing details"',
    ):
        assert marker in source

    assert 'my_work_only = st.checkbox("My Work view"' not in source


def test_my_work_has_clear_daily_navigation() -> None:
    source = Path("pages/35_CommandCore_My_Work.py").read_text(encoding="utf-8")

    for marker in (
        'label="← Command Center"',
        'label="Pipeline & Follow-Up"',
        'label="Unified Deal Record"',
    ):
        assert marker in source
