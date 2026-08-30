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


def test_empty_my_work_view_gives_useful_next_actions() -> None:
    source = Path("pages/35_CommandCore_My_Work.py").read_text(encoding="utf-8")

    for marker in (
        'st.markdown("### You\'re caught up for this view")',
        '"Review Follow-Up & Pipeline"',
        'st.switch_page("pages/46_CommandCore_Pipeline_Followup.py")',
        '"Add New Lead"',
        'st.switch_page("pages/44_CommandCore_CRM.py")',
        'CommandCore will place new assigned work here automatically',
    ):
        assert marker in source


def test_my_work_uses_sidebar_instead_of_duplicate_top_navigation() -> None:
    source = Path("pages/35_CommandCore_My_Work.py").read_text(encoding="utf-8")

    assert 'label="← Command Center"' not in source
    assert 'label="Pipeline & Follow-Up"' not in source
    assert 'label="Unified Deal Record"' not in source
