from pathlib import Path


def coverage_source() -> str:
    return Path("pages/36_CommandCore_Coverage.py").read_text(encoding="utf-8")


def test_coverage_hides_ids_from_normal_workflow() -> None:
    source = coverage_source()

    assert 'st.subheader("Work Needing Coverage")' in source
    assert 'with st.expander("Technical details", expanded=False):' in source
    normal = source[: source.index('with st.expander("Technical details", expanded=False):')]
    assert '"Dispatch": item.get("dispatch_id"' not in normal
    assert 'Backup owner ID:' not in normal


def test_coverage_keeps_safe_reassignment_boundary() -> None:
    source = coverage_source()

    assert '"apply": False' in source
    assert '"apply": True' in source
    assert 'st.button("Route Selected Work to Backup", type="primary")' in source
    assert "Coverage controls affect internal task assignment only" in source


def test_coverage_empty_and_healthy_states_have_next_actions() -> None:
    source = coverage_source()

    for marker in (
        '"Review Team Health"',
        '"Open Operations"',
        '"Open My Work"',
        '"Review Follow-Up & Pipeline"',
        '"Open Coverage Exceptions"',
    ):
        assert marker in source
