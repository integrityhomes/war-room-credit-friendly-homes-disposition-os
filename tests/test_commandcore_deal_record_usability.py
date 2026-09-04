from pathlib import Path


def test_deal_record_uses_clear_work_order_tabs_without_duplicate_top_navigation() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")

    for marker in (
        '"Next Step"',
        '"Messages"',
        '"Offers & Approval"',
        '"Documents & Closing"',
        'label="Open Owner Approvals"',
        'st.markdown("### What should happen next?")',
    ):
        assert marker in source

    assert 'label="← Command Center"' not in source
    assert 'label="Leads & CRM"' not in source
    assert 'label="Pipeline & Follow-Up"' not in source


def test_empty_deal_workspace_guides_user_to_add_first_lead() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")

    for marker in (
        'st.markdown("### No deals yet")',
        'st.button("Add Your First Lead"',
        'st.switch_page("pages/44_CommandCore_CRM.py")',
        'You do not need to create separate seller, property, and deal records manually.',
    ):
        assert marker in source


def test_closing_and_transactions_are_grouped_with_documents() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")

    closing_start = source.index("with closing_tab:")
    history_start = source.index("with history_tab:")
    closing_block = source[closing_start:history_start]
    history_block = source[history_start:]

    assert 'show_related_table("documents", related["documents"])' in closing_block
    assert 'show_related_table("transactions", related["transactions"])' in closing_block
    assert 'show_related_table("transactions", related["transactions"])' not in history_block


def test_deal_overview_surfaces_daily_operating_summary() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")
    overview = source.split("with overview:", 1)[1].split("with next_step_tab:", 1)[0]

    for marker in (
        'st.markdown("### Deal at a glance")',
        'metric("Deal owner"',
        'metric("Next task / follow-up"',
        'metric("Approvals needing attention"',
        'st.markdown("#### Latest communication")',
        'st.markdown("#### Latest activity")',
        'metric("Offer"',
        'metric("Contract / documents"',
        'metric("Title / closing"',
        'metric("Marketing / disposition"',
        'label="Review owner approvals"',
    ):
        assert marker in overview

    assert "build_deal_summary(related)" in source
