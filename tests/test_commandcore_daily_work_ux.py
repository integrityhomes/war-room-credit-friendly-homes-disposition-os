from pathlib import Path

PAGES = {
    "home": Path("pages/00_CommandCore.py").read_text(encoding="utf-8"),
    "leads": Path("pages/44_CommandCore_CRM.py").read_text(encoding="utf-8"),
    "work": Path("pages/35_CommandCore_My_Work.py").read_text(encoding="utf-8"),
    "deal": Path("pages/45_CommandCore_Deal_Record.py").read_text(encoding="utf-8"),
}


def test_daily_pages_use_shared_plain_english_headers() -> None:
    for source in PAGES.values():
        assert "render_page_header(" in source

    assert '"Home"' in PAGES["home"]
    assert '"Leads / Sellers"' in PAGES["leads"]
    assert '"My Work"' in PAGES["work"]
    assert '"Deal Workspace"' in PAGES["deal"]


def test_daily_pages_keep_secondary_information_in_advanced_settings() -> None:
    for source in PAGES.values():
        assert "with advanced_settings():" in source

    assert "supporting_metrics" in PAGES["home"]
    assert "supporting_metrics" in PAGES["work"]
    assert "financial_summary" in PAGES["deal"]


def test_daily_actions_show_persistent_next_step_guidance() -> None:
    assert "queue_success(" in PAGES["leads"]
    assert "show_queued_success()" in PAGES["work"]
    assert "queue_success(" in PAGES["deal"]
    assert "show_queued_success()" in PAGES["deal"]
    assert '**What to do next:**' in Path(
        "src/cfh_disposition/commandcore_ux.py"
    ).read_text(encoding="utf-8")


def test_deal_primary_next_action_preserves_existing_workflows() -> None:
    source = PAGES["deal"]

    assert 'st.button(NEXT, key=f"deal_primary_next_{deal_id}"' in source
    assert 'open_deal_tab("Tasks" if next_task else "Next Step")' in source
    assert '"Offers & Approval"' in source
    assert '"Documents & Closing"' in source
    assert '"pages/48_CommandCore_Owner_Approvals.py"' in source
