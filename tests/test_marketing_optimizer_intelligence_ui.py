from pathlib import Path


PAGE = Path("pages/11_AI_Marketing_Optimizer.py")


def page_source() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_optimizer_surfaces_market_intelligence_after_measured_decisions() -> None:
    source = page_source()

    measured_index = source.index('st.write("### Current measured decisions")')
    intelligence_index = source.index('st.write("### Market Intelligence Test Ideas")')
    assert measured_index < intelligence_index
    assert "build_market_informed_tests" in source
    assert "build_planner_improvement_briefs" in source


def test_market_intelligence_is_fail_open_for_existing_optimizer() -> None:
    source = page_source()

    assert "except MarketingIntelligenceStoreError:" in source
    assert 'return []' in source
    assert "The measured optimizer continues normally." in source


def test_research_section_is_read_only_and_preserves_measured_authority() -> None:
    source = page_source()

    assert "Competitor visibility never overrides CommandCore's own measured scale, pause, or repair decision." in source
    assert "Owner approval required" in source
    assert "intelligence_rows = _market_intelligence_rows(performance)" in source
