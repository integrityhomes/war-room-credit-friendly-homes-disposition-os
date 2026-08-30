from cfh_disposition.marketing_intelligence_sources import ResearchSource
from cfh_disposition.marketing_research_agent import ResearchJobState, build_research_plan


def jobs_by_source(plan):
    return {job.source: job for job in plan.jobs if not job.target}


def test_public_competitor_websites_are_automatic_ready_and_deduplicated() -> None:
    plan = build_research_plan(
        competitor_urls=[
            "https://example.com/blog",
            "https://example.com/blog",
            "not-a-url",
        ],
        include_public_ad_research=False,
        include_owned_performance=False,
    )

    assert len(plan.jobs) == 1
    job = plan.jobs[0]
    assert job.source == ResearchSource.PUBLIC_COMPETITOR_WEBSITE
    assert job.state == ResearchJobState.AUTOMATIC_READY
    assert job.target == "https://example.com/blog"
    assert "never copy protected text" in job.instructions


def test_public_google_and_meta_surfaces_remain_human_review_only() -> None:
    plan = build_research_plan(
        include_public_ad_research=True,
        include_owned_performance=False,
    )
    by_source = jobs_by_source(plan)

    assert by_source[ResearchSource.GOOGLE_ADS_TRANSPARENCY].state == ResearchJobState.HUMAN_REVIEW_REQUIRED
    assert by_source[ResearchSource.META_AD_LIBRARY_PUBLIC].state == ResearchJobState.HUMAN_REVIEW_REQUIRED
    assert by_source[ResearchSource.META_AD_LIBRARY_API].state == ResearchJobState.AUTHORIZATION_REQUIRED


def test_authorized_official_sources_become_automatic_ready() -> None:
    plan = build_research_plan(
        google_ads_authorized=True,
        google_search_console_authorized=True,
        meta_ad_library_api_authorized=True,
    )
    by_source = jobs_by_source(plan)

    assert by_source[ResearchSource.GOOGLE_ADS_OWN_ACCOUNT].state == ResearchJobState.AUTOMATIC_READY
    assert by_source[ResearchSource.GOOGLE_SEARCH_CONSOLE].state == ResearchJobState.AUTOMATIC_READY
    assert by_source[ResearchSource.META_AD_LIBRARY_API].state == ResearchJobState.AUTOMATIC_READY


def test_unapproved_owned_sources_never_run_automatically() -> None:
    plan = build_research_plan()
    by_source = jobs_by_source(plan)

    assert by_source[ResearchSource.GOOGLE_ADS_OWN_ACCOUNT].state == ResearchJobState.AUTHORIZATION_REQUIRED
    assert by_source[ResearchSource.GOOGLE_SEARCH_CONSOLE].state == ResearchJobState.AUTHORIZATION_REQUIRED
    assert not any(
        job.source in {ResearchSource.GOOGLE_ADS_OWN_ACCOUNT, ResearchSource.GOOGLE_SEARCH_CONSOLE}
        for job in plan.automatic_jobs
    )
