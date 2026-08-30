from cfh_disposition.marketing_intelligence import (
    IntelligenceSurface,
    MarketObservation,
    build_intelligence_brief,
)


def test_repeated_market_pattern_becomes_test_recommendation() -> None:
    rows = [
        MarketObservation(
            surface=IntelligenceSurface.META_ADS,
            market="Decatur IL",
            source_name="Competitor A",
            headline_or_topic="Flexible homeownership options",
            hook="Low move-in amount",
        ),
        MarketObservation(
            surface=IntelligenceSurface.META_ADS,
            market="Decatur IL",
            source_name="Competitor B",
            headline_or_topic="Homes with flexible terms",
            hook="Low move-in amount",
        ),
    ]

    brief = build_intelligence_brief(rows)

    assert brief.observations_reviewed == 2
    assert any(item.pattern == "Low move-in amount" for item in brief.patterns)
    assert all("copying" in item.commandcore_test for item in brief.patterns)


def test_single_observation_is_not_called_a_winner() -> None:
    brief = build_intelligence_brief(
        [
            MarketObservation(
                surface=IntelligenceSurface.BLOG,
                market="Peoria IL",
                source_name="Competitor Blog",
                headline_or_topic="How owner financing works",
                keyword_or_intent="owner financing Peoria",
            )
        ]
    )

    assert brief.patterns == []
    assert any("does not prove" in warning for warning in brief.cautions)


def test_intelligence_supports_paid_and_organic_surfaces() -> None:
    supported = set(IntelligenceSurface)
    assert IntelligenceSurface.GOOGLE_ADS in supported
    assert IntelligenceSurface.META_ADS in supported
    assert IntelligenceSurface.CHATGPT_ADS in supported
    assert IntelligenceSurface.BLOG in supported
    assert IntelligenceSurface.MARKET_SEO in supported
    assert IntelligenceSurface.LANDING_PAGE in supported
