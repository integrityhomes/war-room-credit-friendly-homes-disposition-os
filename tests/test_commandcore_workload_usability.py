from pathlib import Path


def workload_source() -> str:
    return Path("pages/41_CommandCore_Workload_Balance.py").read_text(encoding="utf-8")


def test_workload_empty_state_has_safe_next_actions() -> None:
    source = workload_source()

    for marker in (
        'st.markdown("### No workload move is recommended right now")',
        '"Review Team Health"',
        'st.switch_page("pages/40_CommandCore_Team_Health.py")',
        '"Review My Work"',
        'st.switch_page("pages/35_CommandCore_My_Work.py")',
    ):
        assert marker in source


def test_workload_recommendation_heading_avoids_internal_ids() -> None:
    source = workload_source()
    function_start = source.index("def recommendation_label")
    function_end = source.index("\n\n\nrequire_password()", function_start)
    label_function = source[function_start:function_end]

    assert "property_id" not in label_function
    assert "dispatch_id" not in label_function
    assert "from_owner_name" in label_function
    assert "to_owner_name" in label_function


def test_workload_preserves_human_approval_and_moves_ids_to_details() -> None:
    source = workload_source()

    for marker in (
        '"Approve this internal workload move"',
        '"Apply Safe Rebalance"',
        '"apply": True',
        'with st.expander("Technical details", expanded=False):',
        '"Property ID": recommendation.get("property_id")',
        '"Dispatch ID": recommendation.get("dispatch_id")',
    ):
        assert marker in source
