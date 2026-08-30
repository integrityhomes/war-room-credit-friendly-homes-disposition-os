from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from .marketing_intelligence_sources import ResearchSource, source_policy


class ResearchJobState(StrEnum):
    AUTOMATIC_READY = "automatic_ready"
    AUTHORIZATION_REQUIRED = "authorization_required"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


@dataclass(frozen=True, slots=True)
class ResearchJob:
    source: ResearchSource
    state: ResearchJobState
    purpose: str
    target: str = ""
    instructions: str = ""


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    jobs: tuple[ResearchJob, ...]

    @property
    def automatic_jobs(self) -> tuple[ResearchJob, ...]:
        return tuple(job for job in self.jobs if job.state == ResearchJobState.AUTOMATIC_READY)

    @property
    def authorization_jobs(self) -> tuple[ResearchJob, ...]:
        return tuple(job for job in self.jobs if job.state == ResearchJobState.AUTHORIZATION_REQUIRED)

    @property
    def human_review_jobs(self) -> tuple[ResearchJob, ...]:
        return tuple(job for job in self.jobs if job.state == ResearchJobState.HUMAN_REVIEW_REQUIRED)


def _clean_public_url(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return candidate


def _source_job(
    source: ResearchSource,
    *,
    authorized: bool,
    target: str = "",
    instructions: str = "",
) -> ResearchJob:
    policy = source_policy(source)
    if policy.automated_collection_allowed:
        state = (
            ResearchJobState.AUTOMATIC_READY
            if not policy.requires_account_authorization or authorized
            else ResearchJobState.AUTHORIZATION_REQUIRED
        )
    else:
        state = ResearchJobState.HUMAN_REVIEW_REQUIRED
    return ResearchJob(
        source=source,
        state=state,
        purpose=policy.purpose,
        target=target,
        instructions=instructions or policy.notes,
    )


def build_research_plan(
    *,
    competitor_urls: list[str] | tuple[str, ...] = (),
    google_ads_authorized: bool = False,
    google_search_console_authorized: bool = False,
    meta_ad_library_api_authorized: bool = False,
    include_public_ad_research: bool = True,
    include_owned_performance: bool = True,
) -> ResearchPlan:
    """Build the safe work plan for the Marketing Intelligence Research Agent.

    The plan is deliberately explicit about what may run automatically. Public Google
    and Meta research surfaces remain human-review tasks unless an approved API exists.
    Owned account data never becomes automatic until the corresponding account is
    authorized. Public competitor websites may be collected automatically, subject to
    robots/access restrictions enforced by the collector.
    """

    jobs: list[ResearchJob] = []
    seen_urls: set[str] = set()
    for raw_url in competitor_urls:
        url = _clean_public_url(raw_url)
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        jobs.append(
            _source_job(
                ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
                authorized=True,
                target=url,
                instructions=(
                    "Review public page structure, offers, calls to action, blog/SEO themes, and reusable patterns. "
                    "Respect robots/access restrictions and never copy protected text."
                ),
            )
        )

    if include_public_ad_research:
        jobs.extend(
            [
                _source_job(
                    ResearchSource.GOOGLE_ADS_TRANSPARENCY,
                    authorized=False,
                    instructions=(
                        "Review active advertiser messaging through Google's public transparency surface. "
                        "Record patterns and evidence only; do not scrape the Google property."
                    ),
                ),
                _source_job(
                    ResearchSource.META_AD_LIBRARY_PUBLIC,
                    authorized=False,
                    instructions=(
                        "Review currently running public Meta ads. Record hooks, offers, formats, and calls to action; "
                        "do not treat visibility as proof of spend or profitability."
                    ),
                ),
                _source_job(
                    ResearchSource.META_AD_LIBRARY_API,
                    authorized=meta_ad_library_api_authorized,
                    instructions=(
                        "Use only Meta-supported Ad Library API categories, regions, permissions, and fields."
                    ),
                ),
            ]
        )

    if include_owned_performance:
        jobs.extend(
            [
                _source_job(
                    ResearchSource.GOOGLE_ADS_OWN_ACCOUNT,
                    authorized=google_ads_authorized,
                ),
                _source_job(
                    ResearchSource.GOOGLE_SEARCH_CONSOLE,
                    authorized=google_search_console_authorized,
                ),
            ]
        )

    return ResearchPlan(jobs=tuple(jobs))
