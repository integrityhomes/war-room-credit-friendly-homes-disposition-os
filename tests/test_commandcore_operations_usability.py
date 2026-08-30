from pathlib import Path


def operations_source() -> str:
    return Path("pages/39_CommandCore_Operations_Hub.py").read_text(encoding="utf-8")


def test_operations_starts_with_management_attention_not_system_internals() -> None:
    source = operations_source()

    assert 'st.title("CommandCore Operations")' in source
    attention_index = source.index('st.subheader("Needs Management Attention")')
    readiness_index = source.index('with st.expander("System readiness & CRM cutover", expanded=False):')
    assert attention_index < readiness_index


def test_operations_prioritizes_handle_these_first() -> None:
    source = operations_source()

    for marker in (
        'st.subheader("Handle These First")',
        'expanded=int(item.get("rank", 9)) <= 2',
        'st.write(f"**Do this next:**',
        'with st.expander("More alert detail", expanded=False):',
    ):
        assert marker in source


def test_clear_management_queue_has_safe_next_actions() -> None:
    source = operations_source()

    for marker in (
        'st.markdown("### Management queue is clear")',
        '"Review Owner Approvals"',
        'st.switch_page("pages/48_CommandCore_Owner_Approvals.py")',
        '"Review My Work"',
        'st.switch_page("pages/35_CommandCore_My_Work.py")',
    ):
        assert marker in source


def test_system_readiness_and_crm_cutover_are_preserved() -> None:
    source = operations_source()

    for marker in (
        'def load_launch_readiness()',
        'def render_system_readiness(',
        'st.subheader("CommandCore System Readiness")',
        'st.markdown("#### CRM Replacement / Cutover")',
        '"Do not discontinue the outside CRM yet."',
    ):
        assert marker in source
