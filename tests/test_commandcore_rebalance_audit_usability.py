from pathlib import Path


def audit_source() -> str:
    return Path("pages/42_CommandCore_Rebalance_Audit.py").read_text(encoding="utf-8")


def test_workload_audit_summarizes_business_results_first() -> None:
    source = audit_source()

    for marker in (
        'st.subheader("Recent Automatic Workload Reviews")',
        '"What moved"',
        '"Why some moves were skipped"',
        'with st.expander("Technical audit details", expanded=False):',
    ):
        assert marker in source

    moved = source.index('st.markdown("**What moved**")')
    technical = source.index('with st.expander("Technical audit details", expanded=False):')
    assert moved < technical


def test_workload_audit_keeps_identifiers_in_technical_details() -> None:
    source = audit_source()

    technical = source[source.index('with st.expander("Technical audit details", expanded=False):'):]
    for marker in ("from_owner_id", "to_owner_id", "dispatch_id", "action_id"):
        assert marker in technical


def test_empty_workload_audit_has_safe_next_actions() -> None:
    source = audit_source()

    for marker in (
        'st.markdown("### No automatic workload audit runs yet")',
        '"Review Workload"',
        'st.switch_page("pages/41_CommandCore_Workload_Balance.py")',
        '"Review Team Health"',
        'st.switch_page("pages/40_CommandCore_Team_Health.py")',
    ):
        assert marker in source
