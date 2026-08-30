from datetime import UTC, datetime, timedelta

from cfh_disposition.marketing_intelligence import IntelligenceSurface, MarketObservation
from cfh_disposition.marketing_intelligence_pipeline import (
    build_current_intelligence_brief,
    recent_observations,
)
from cfh_disposition.marketing_intelligence_store import (
    MarketingIntelligenceLedger,
    upsert_observation,
)


def observation(topic: str) -> MarketObservation:
    return MarketObservation(
        surface=IntelligenceSurface.BLOG,
        market="Decatur",
        source_name="Competitor",
        source_url=f"https://example.com/{topic.replace(' ', '-').lower()}",
        headline_or_topic=topic,
        keyword_or_intent="owner financing decatur il",
    )


def test_recent_observations_exclude_stale_research() -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    ledger = upsert_observation(
        MarketingIntelligenceLedger(),
        observation("Fresh topic"),
        observed_at=now - timedelta(days=10),
    )
    ledger = upsert_observation(
        ledger,
        observation("Stale topic"),
        observed_at=now - timedelta(days=120),
    )

    rows = recent_observations(ledger, now=now, lookback_days=90)

    assert [row.headline_or_topic for row in rows] == ["Fresh topic"]


def test_current_brief_uses_only_recent_repeated_patterns() -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    ledger = MarketingIntelligenceLedger()
    for source in ("one", "two"):
        row = MarketObservation(
            surface=IntelligenceSurface.BLOG,
            market="Decatur",
            source_name=source,
            source_url=f"https://{source}.example.com/article",
            headline_or_topic="Low down payment owner financing",
        )
        ledger = upsert_observation(
            ledger,
            row,
            observed_at=now - timedelta(days=5),
        )

    brief = build_current_intelligence_brief(ledger, now=now)

    assert brief.observations_reviewed == 2
    assert len(brief.patterns) == 1
    assert brief.patterns[0].occurrences == 2


def test_empty_recent_window_warns_against_stale_inference() -> None:
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    ledger = upsert_observation(
        MarketingIntelligenceLedger(),
        observation("Old topic"),
        observed_at=now - timedelta(days=200),
    )

    brief = build_current_intelligence_brief(ledger, now=now, lookback_days=30)

    assert brief.observations_reviewed == 0
    assert any("stale research" in caution.lower() for caution in brief.cautions)
