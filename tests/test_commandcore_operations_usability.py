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


def test_owner_only_property_source_diagnostic_is_safe_and_plain_english() -> None:
    source = operations_source()

    for marker in (
        'with st.expander("Property Source Diagnostics", expanded=False):',
        '"Run 3-Property Read-Only Test"',
        'run_property_source_diagnostic(st.secrets)',
        '"Live Google connection: PASS"',
        'status_left.metric("Read-only scope", "PASS")',
        'status_middle.metric("Rows read", diagnostic.rows_read)',
        'status_right.metric("Rows written", diagnostic.google_writes)',
        '"CommandCore records created: 0 · Google writes: 0 · Sensitive data exposed: No"',
    ):
        assert marker in source

    diagnostic_index = source.index(
        'with st.expander("Property Source Diagnostics", expanded=False):'
    )
    operations_load_index = source.index("queue_items = load_queue_items()")
    assert diagnostic_index < operations_load_index

    diagnostic_block = source[diagnostic_index:operations_load_index]
    for forbidden in (
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "GOOGLE_SHEET_ID",
        "lockbox",
        "seller_email",
        "notes",
    ):
        assert forbidden not in diagnostic_block


def test_full_property_source_audit_shows_summary_not_full_source() -> None:
    source = operations_source()

    for marker in (
        '"Run Full Property Source Audit"',
        "run_full_property_source_audit(st.secrets)",
        '"Full Google property source: PASS"',
        'st.markdown("#### Properties by source tab")',
        'st.markdown("#### Safe sample properties")',
        'safe_rows[:5]',
        'with st.expander("Inspect additional safe previews", expanded=False):',
        "safe_rows[5:25]",
    ):
        assert marker in source


def test_property_diagnostic_failures_show_only_allowlisted_safe_details() -> None:
    source = operations_source()

    assert source.count("safe_property_diagnostic_failure(error)") == 2
    assert source.count('st.write(f"**Failure category:** {failure.category.value}")') == 2
    assert source.count('st.write(f"**Safe explanation:** {failure.explanation}")') == 2
    assert "str(error)" not in source
    assert "st.exception" not in source


def test_secretary_test_panel_is_plain_english_and_cannot_execute() -> None:
    source = operations_source()

    for marker in (
        'with st.expander("Nevaeh Test", expanded=False):',
        '"Nevaeh — CommandCore Secretary can evaluate an existing CommandCore communication or a safe test message. "',
        'st.warning("TEST MODE — NOTHING WILL BE SENT OR CHANGED")',
        '"Evaluate in Test Mode"',
        'st.markdown("### Nevaeh Result")',
        '"**Person:**',
        '"**Relationship:**',
        '"**Related property:**',
        '"**Related deal:**',
        '"**Current deal owner:**',
        '"**What they appear to want:**',
        '"**Recommended next step:**',
        '"**Who should handle it:**',
        '"**Approval required:**',
        '"**Draft response, if safe:** "',
        '"No external action, record write, message, call, approval, consent change, or task was started."',
    ):
        assert marker in source

    secretary_start = source.index('with st.expander("Nevaeh Test", expanded=False):')
    property_diagnostics = source.index(
        'with st.expander("Property Source Diagnostics", expanded=False):'
    )
    secretary_panel = source[secretary_start:property_diagnostics]
    for forbidden in ("send_sms", "send_email", "make_call", "upsert", "post_commandcore"):
        assert forbidden not in secretary_panel.casefold()


def test_nevaeh_inbox_is_read_only_plain_english_and_prioritized() -> None:
    source = operations_source()

    for marker in (
        'with st.expander("Nevaeh Inbox", expanded=True):',
        'st.warning("NEVAEH — TEST MODE\\n\\nNOTHING WILL BE SENT")',
        'list_secretary_crm_records("communications")',
        "build_nevaeh_inbox(",
        "for column, category in zip(summary_columns, NevaehInboxCategory, strict=True):",
        'column.metric(category.value, category_counts[category.value])',
        '"Nevaeh classification": item.classification',
        '"Recommended next step": item.recommended_next_step',
        '"Approval required": "Yes" if item.approval_required else "No"',
        '"Nevaeh cannot send, call, approve, or change legal or financial terms."',
    ):
        assert marker in source

    inbox_start = source.index('with st.expander("Nevaeh Inbox", expanded=True):')
    test_start = source.index('with st.expander("Nevaeh Test", expanded=False):')
    inbox_panel = source[inbox_start:test_start]
    for forbidden in ("post_commandcore", "upsert", "insert", "update", "delete", "send_sms", "send_email", "make_call"):
        assert forbidden not in inbox_panel.casefold()


def test_secretary_phase_two_uses_only_existing_crm_read_actions() -> None:
    source = operations_source()

    for marker in (
        '"Existing CommandCore Communication"',
        'list_secretary_crm_records("communications")',
        'list_secretary_crm_records("contacts")',
        'list_secretary_crm_records("properties")',
        'list_secretary_crm_records("deals")',
        '"action": "list"',
        '"Evaluate Existing Communication"',
        'st.markdown("### Match Quality")',
        '"**Contact match:**',
        '"**Property match:**',
        '"**Deal match:**',
        '"**Routing source:**',
        '"**Consent state:**',
        '"commandcore-contact-ledger"',
        '"action": "evaluate_contact"',
        "read_secretary_consent(",
    ):
        assert marker in source

    read_helper = source[source.index("def list_secretary_crm_records"):source.index("def post_commandcore")]
    for forbidden in ("upsert", "insert", "update", "delete", "create"):
        assert forbidden not in read_helper.casefold()

    consent_helper = source[
        source.index("def read_secretary_consent"):source.index("def post_commandcore")
    ]
    for forbidden in ("record_consent", "upsert_contact", "insert", "update", "delete"):
        assert forbidden not in consent_helper.casefold()
