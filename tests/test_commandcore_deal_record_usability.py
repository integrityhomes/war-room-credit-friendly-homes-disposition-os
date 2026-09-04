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


def test_deal_summary_quick_actions_open_existing_workflows_only() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")
    overview = source.split("with overview:", 1)[1].split("with next_step_tab:", 1)[0]

    for marker in (
        '"View Next Task"',
        'open_deal_tab("Tasks")',
        '"View Communications"',
        'open_deal_tab("Messages")',
        '"View Recent Activity"',
        'open_deal_tab("History")',
        '"Review Offers"',
        '"Start Offer Review"',
        'open_deal_tab("Offers & Approval")',
        '"Open Documents & Closing"',
        'open_deal_tab("Documents & Closing")',
        '"Open Marketing"',
        'open_marketing(property_record)',
        'label="Review Approval"',
    ):
        assert marker in overview

    assert "These actions do not send, approve, sign, or publish anything." in overview
    assert 'if next_task and action_columns' in overview
    assert 'if latest_message and action_columns' in overview
    assert 'if latest_activity and action_columns' in overview
    assert 'if deal_summary.approval_count:' in overview
    assert 'if property_record and action_columns' in overview


def test_deal_overview_shows_read_only_owner_approval_status() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")
    overview = source.split("with overview:", 1)[1].split("with next_step_tab:", 1)[0]

    for marker in (
        'st.markdown("#### Approval Status")',
        "No approval is currently waiting, and no owner decision history is recorded for this Deal.",
        'st.write(f"Decision made by: {approval.decided_by}")',
        "approval_decision_time_label(approval.decided_at)",
        'st.write(f"Next step: {approval.next_step}")',
        "if approval.actionable:",
        'label="Review Approval"',
        '"pages/48_CommandCore_Owner_Approvals.py"',
    ):
        assert marker in overview

    assert 'build_deal_approval_status(related["offers"], related["documents"])' in source
    assert "OWNER_APPROVAL_PIN" not in overview
    assert "approval.id" not in overview


def test_deal_quick_actions_select_existing_keyed_tabs() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")

    assert 'st.session_state["commandcore_deal_pending_tab"] = label' in source
    assert 'st.session_state["commandcore_deal_tabs"] = pending_tab' in source
    assert 'key="commandcore_deal_tabs"' in source


def test_deal_tasks_tab_schedules_shared_followup_in_current_deal() -> None:
    source = Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8")
    tasks = source.split("with tasks_tab:", 1)[1].split("with messages_tab:", 1)[0]

    for marker in (
        'st.markdown("### Next follow-up")',
        'st.markdown("### Schedule follow-up")',
        '"Follow-up note"',
        'date_input("Due date"',
        'time_input("Due time"',
        '"Assigned to"',
        'value=text(deal.get("assigned_to"))',
        'st.form_submit_button("Schedule Follow-Up"',
        "build_followup_record(",
        "deal_id=deal_id",
        'save_related("tasks", deal_id, record)',
        'st.success("Follow-up scheduled. No message or call was made.")',
        "st.rerun()",
    ):
        assert marker in tasks

    assert "Mark Complete" not in tasks
    assert "mark complete" not in tasks.lower()
