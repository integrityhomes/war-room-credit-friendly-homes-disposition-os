from cfh_disposition.marketing_intelligence import IntelligenceSurface
from cfh_disposition.marketing_intelligence_optimizer import IntelligenceTestCandidate
from cfh_disposition.marketing_intelligence_planner import build_planner_improvement_briefs


def candidate(surface: IntelligenceSurface, channel_key: str | None) -> IntelligenceTestCandidate:
    return IntelligenceTestCandidate(
        surface=surface,
        channel_key=channel_key,
        market="Decatur",
        observed_pattern="Lead with exact monthly payment",
        occurrences=3,
        measured_channel_decision="Keep Running",
        recommendation="Use this as a controlled challenger test, not as evidence to scale.",
        commandcore_test="Create an original challenger using the payment-first angle.",
        evidence_rule="Our own measured results control scale decisions.",
    )


def test_paid_ads_brief_requires_owner_approval_and_cannot_auto_publish() -> None:
    brief = build_planner_improvement_briefs(
        [candidate(IntelligenceSurface.META_ADS, "meta_ads")]
    )[0]

    assert brief.requires_owner_approval is True
    assert brief.can_publish_automatically is False
    assert brief.copy_source_text is False


def test_blog_brief_remains_approval_gated() -> None:
    brief = build_planner_improvement_briefs(
        [candidate(IntelligenceSurface.BLOG, "blog")]
    )[0]

    assert brief.requires_owner_approval is False
    assert brief.can_publish_automatically is False
    assert brief.copy_source_text is False


def test_market_seo_brief_can_flow_to_existing_automatic_owned_web_path() -> None:
    brief = build_planner_improvement_briefs(
        [candidate(IntelligenceSurface.MARKET_SEO, "market_seo")]
    )[0]

    assert brief.requires_owner_approval is False
    assert brief.can_publish_automatically is True


def test_measured_decision_and_recommendation_are_preserved() -> None:
    item = candidate(IntelligenceSurface.GOOGLE_ADS, "google_ads")
    brief = build_planner_improvement_briefs([item])[0]

    assert brief.measured_decision == item.measured_channel_decision
    assert brief.recommended_action == item.recommendation
    assert brief.test_angle == item.commandcore_test
