from cfh_disposition.marketing_intelligence import (
    IntelligenceBrief,
    IntelligenceSurface,
    WinningPattern,
)
from cfh_disposition.marketing_intelligence_optimizer import build_market_informed_tests


def brief_for(surface: IntelligenceSurface) -> IntelligenceBrief:
    return IntelligenceBrief(
        observations_reviewed=4,
        patterns=[
            WinningPattern(
                surface=surface,
                market="Decatur",
                pattern="Lead with exact monthly payment",
                occurrences=3,
                why_it_may_work="Repeated observable pattern.",
                commandcore_test="Create an original challenger using the payment-first angle.",
                confidence="Medium",
            )
        ],
        cautions=["Research is not proof of profitability."],
    )


def test_market_pattern_cannot_turn_pause_into_scale() -> None:
    candidates = build_market_informed_tests(
        brief_for(IntelligenceSurface.META_ADS),
        {"meta_ads": "Pause Spend"},
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.channel_key == "meta_ads"
    assert candidate.measured_channel_decision == "Pause Spend"
    assert "hold" in candidate.recommendation.lower()
    assert "scale" in candidate.evidence_rule.lower()


def test_repair_signal_keeps_research_as_repair_test_only() -> None:
    candidates = build_market_informed_tests(
        brief_for(IntelligenceSurface.GOOGLE_ADS),
        {"google_ads": "Repair Funnel"},
    )

    assert "repair-test" in candidates[0].recommendation.lower()
    assert "do not increase spend" in candidates[0].recommendation.lower()


def test_blog_pattern_can_become_controlled_challenger_without_measured_channel_data() -> None:
    candidates = build_market_informed_tests(
        brief_for(IntelligenceSurface.BLOG),
        {},
    )

    candidate = candidates[0]
    assert candidate.channel_key == "blog"
    assert candidate.measured_channel_decision == "No measured decision"
    assert "controlled challenger" in candidate.recommendation.lower()
    assert "not as evidence to scale" in candidate.recommendation.lower()
