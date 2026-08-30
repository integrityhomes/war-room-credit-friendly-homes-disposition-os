from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ResearchSource(StrEnum):
    GOOGLE_ADS_TRANSPARENCY = "google_ads_transparency"
    GOOGLE_SEARCH_RESULTS = "google_search_results"
    GOOGLE_ADS_OWN_ACCOUNT = "google_ads_own_account"
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    META_AD_LIBRARY_PUBLIC = "meta_ad_library_public"
    META_AD_LIBRARY_API = "meta_ad_library_api"
    PUBLIC_COMPETITOR_WEBSITE = "public_competitor_website"


class SourcePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: ResearchSource
    purpose: str
    automated_collection_allowed: bool
    requires_account_authorization: bool
    competitor_research: bool
    notes: str


SOURCE_POLICIES: dict[ResearchSource, SourcePolicy] = {
    ResearchSource.GOOGLE_ADS_TRANSPARENCY: SourcePolicy(
        source=ResearchSource.GOOGLE_ADS_TRANSPARENCY,
        purpose="Review active Google advertiser creative and messaging through Google's transparency surface.",
        automated_collection_allowed=False,
        requires_account_authorization=False,
        competitor_research=True,
        notes=(
            "Do not scrape Google properties. Treat this as a permitted review/research source unless Google provides an approved API for the intended region/use case."
        ),
    ),
    ResearchSource.GOOGLE_SEARCH_RESULTS: SourcePolicy(
        source=ResearchSource.GOOGLE_SEARCH_RESULTS,
        purpose="Understand search intent and discover public competitor pages.",
        automated_collection_allowed=False,
        requires_account_authorization=False,
        competitor_research=True,
        notes=(
            "Do not scrape Google Search result pages or purchase scraped Google data. Use an approved search provider or other lawful discovery source instead."
        ),
    ),
    ResearchSource.GOOGLE_ADS_OWN_ACCOUNT: SourcePolicy(
        source=ResearchSource.GOOGLE_ADS_OWN_ACCOUNT,
        purpose="Measure CommandCore-owned Google Ads performance and campaign data.",
        automated_collection_allowed=True,
        requires_account_authorization=True,
        competitor_research=False,
        notes="Use the official Google Ads API after the account/developer token is authorized.",
    ),
    ResearchSource.GOOGLE_SEARCH_CONSOLE: SourcePolicy(
        source=ResearchSource.GOOGLE_SEARCH_CONSOLE,
        purpose="Measure CommandCore-owned organic search performance for blogs and market SEO pages.",
        automated_collection_allowed=True,
        requires_account_authorization=True,
        competitor_research=False,
        notes="Use the official Search Console API for owned properties after authorization.",
    ),
    ResearchSource.META_AD_LIBRARY_PUBLIC: SourcePolicy(
        source=ResearchSource.META_AD_LIBRARY_PUBLIC,
        purpose="Review currently running public Meta ads by keyword or advertiser.",
        automated_collection_allowed=False,
        requires_account_authorization=False,
        competitor_research=True,
        notes=(
            "Use the public Ad Library as a research surface. Do not bypass access controls or assume public visibility proves spend, targeting, or profitability."
        ),
    ),
    ResearchSource.META_AD_LIBRARY_API: SourcePolicy(
        source=ResearchSource.META_AD_LIBRARY_API,
        purpose="Run supported custom Ad Library queries where Meta makes API data available.",
        automated_collection_allowed=True,
        requires_account_authorization=True,
        competitor_research=True,
        notes=(
            "Use only the categories, regions, fields, and permissions Meta currently exposes through the official API."
        ),
    ),
    ResearchSource.PUBLIC_COMPETITOR_WEBSITE: SourcePolicy(
        source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
        purpose="Study public blog topics, landing-page structure, offers, calls to action, and SEO themes.",
        automated_collection_allowed=True,
        requires_account_authorization=False,
        competitor_research=True,
        notes=(
            "Respect robots/access restrictions and site terms. Extract patterns and facts only; never copy protected article or creative text."
        ),
    ),
}


def source_policy(source: ResearchSource) -> SourcePolicy:
    return SOURCE_POLICIES[source]


def can_collect_automatically(source: ResearchSource, *, authorized: bool = False) -> bool:
    policy = source_policy(source)
    if not policy.automated_collection_allowed:
        return False
    if policy.requires_account_authorization and not authorized:
        return False
    return True
