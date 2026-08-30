from cfh_disposition.marketing_intelligence_sources import (
    ResearchSource,
    can_collect_automatically,
    source_policy,
)


def test_google_properties_are_not_scraped_for_competitor_research() -> None:
    assert not can_collect_automatically(ResearchSource.GOOGLE_SEARCH_RESULTS)
    assert not can_collect_automatically(ResearchSource.GOOGLE_ADS_TRANSPARENCY)
    assert "scrape" in source_policy(ResearchSource.GOOGLE_SEARCH_RESULTS).notes.lower()


def test_owned_google_data_requires_authorization() -> None:
    assert not can_collect_automatically(ResearchSource.GOOGLE_ADS_OWN_ACCOUNT)
    assert can_collect_automatically(
        ResearchSource.GOOGLE_ADS_OWN_ACCOUNT,
        authorized=True,
    )
    assert not can_collect_automatically(ResearchSource.GOOGLE_SEARCH_CONSOLE)
    assert can_collect_automatically(
        ResearchSource.GOOGLE_SEARCH_CONSOLE,
        authorized=True,
    )


def test_meta_api_requires_authorization_but_public_library_is_review_only() -> None:
    assert not can_collect_automatically(ResearchSource.META_AD_LIBRARY_PUBLIC)
    assert not can_collect_automatically(ResearchSource.META_AD_LIBRARY_API)
    assert can_collect_automatically(
        ResearchSource.META_AD_LIBRARY_API,
        authorized=True,
    )


def test_public_competitor_websites_can_feed_pattern_research() -> None:
    assert can_collect_automatically(ResearchSource.PUBLIC_COMPETITOR_WEBSITE)
    policy = source_policy(ResearchSource.PUBLIC_COMPETITOR_WEBSITE)
    assert policy.competitor_research is True
    assert "never copy" in policy.notes.lower()
