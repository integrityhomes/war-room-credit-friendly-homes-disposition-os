from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class IntelligenceSurface(StrEnum):
    GOOGLE_ADS = "google_ads"
    META_ADS = "meta_ads"
    CHATGPT_ADS = "chatgpt_ads"
    BLOG = "blog"
    MARKET_SEO = "market_seo"
    SOCIAL = "social"
    EMAIL = "email"
    SMS = "sms"
    LANDING_PAGE = "landing_page"


class MarketObservation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    surface: IntelligenceSurface
    market: str = Field(min_length=2, max_length=120)
    source_name: str = Field(min_length=2, max_length=200)
    source_url: HttpUrl | None = None
    headline_or_topic: str = Field(min_length=3, max_length=500)
    hook: str = Field(default="", max_length=500)
    offer: str = Field(default="", max_length=500)
    call_to_action: str = Field(default="", max_length=300)
    keyword_or_intent: str = Field(default="", max_length=300)
    creative_pattern: str = Field(default="", max_length=500)
    landing_page_pattern: str = Field(default="", max_length=500)
    evidence_note: str = Field(default="", max_length=1200)


class WinningPattern(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    surface: IntelligenceSurface
    market: str
    pattern: str
    occurrences: int = Field(ge=1)
    why_it_may_work: str
    commandcore_test: str
    confidence: str


class IntelligenceBrief(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    observations_reviewed: int
    patterns: list[WinningPattern]
    cautions: list[str]


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def build_intelligence_brief(observations: Iterable[MarketObservation]) -> IntelligenceBrief:
    rows = list(observations)
    counters: Counter[tuple[IntelligenceSurface, str, str]] = Counter()
    originals: dict[tuple[IntelligenceSurface, str, str], str] = {}

    for row in rows:
        candidates = [
            row.hook,
            row.offer,
            row.call_to_action,
            row.keyword_or_intent,
            row.creative_pattern,
            row.landing_page_pattern,
            row.headline_or_topic,
        ]
        for candidate in candidates:
            if not candidate.strip():
                continue
            key = (row.surface, _normalized(row.market), _normalized(candidate))
            counters[key] += 1
            originals.setdefault(key, candidate.strip())

    patterns: list[WinningPattern] = []
    for (surface, market, normalized_pattern), count in counters.most_common():
        if count < 2:
            continue
        original = originals[(surface, market, normalized_pattern)]
        patterns.append(
            WinningPattern(
                surface=surface,
                market=market.title(),
                pattern=original,
                occurrences=count,
                why_it_may_work=(
                    "This pattern appears repeatedly in observable market activity. Repetition is a research signal, not proof of profitability."
                ),
                commandcore_test=(
                    f"Create an original {surface.value.replace('_', ' ')} challenger using the same underlying angle without copying wording or creative."
                ),
                confidence="Medium" if count >= 3 else "Low",
            )
        )

    return IntelligenceBrief(
        observations_reviewed=len(rows),
        patterns=patterns,
        cautions=[
            "Public visibility does not prove competitor spend, ROAS, conversion rate, or profitability.",
            "Never copy protected creative or article text; use observed patterns only as research inputs.",
            "CommandCore should validate every recommendation against our own tracked clicks, leads, applications, contracts, and cost data before scaling.",
        ],
    )
