from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cfh_disposition.marketing_intelligence import IntelligenceSurface, MarketObservation
from cfh_disposition.marketing_intelligence_collection_pipeline import (
    process_and_save_collected_observation,
    process_collected_observation,
)
from cfh_disposition.marketing_intelligence_ingestion import MarketingIntelligenceIngestionError
from cfh_disposition.marketing_intelligence_sources import ResearchSource
from cfh_disposition.marketing_intelligence_store import MarketingIntelligenceLedger


def observation(headline: str = "Flexible owner financing") -> MarketObservation:
    return MarketObservation(
        surface=IntelligenceSurface.BLOG,
        market="Decatur, IL",
        source_name="Example Homes",
        source_url="https://example.com/blog/owner-financing",
        headline_or_topic=headline,
        hook="Flexible terms",
        call_to_action="See Homes",
        keyword_or_intent="owner financing",
    )


def test_repeat_sighting_increments_existing_observation() -> None:
    first_time = datetime(2026, 8, 29, 12, tzinfo=UTC)
    second_time = datetime(2026, 8, 30, 12, tzinfo=UTC)
    first = process_collected_observation(
        MarketingIntelligenceLedger(),
        source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
        observation=observation(),
        measured_channel_actions={"blog": "Keep Running"},
        observed_at=first_time,
        now=first_time,
    )
    second = process_collected_observation(
        first.ledger,
        source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
        observation=observation(),
        measured_channel_actions={"blog": "Keep Running"},
        observed_at=second_time,
        now=second_time,
    )
    assert len(second.ledger.observations) == 1
    assert second.ledger.observations[0].sightings == 2
    assert second.ledger.observations[0].last_seen_at == second_time


def test_market_pattern_can_only_create_challenger_not_scale_override() -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    ledger = MarketingIntelligenceLedger()
    for index in range(2):
        result = process_collected_observation(
            ledger,
            source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
            observation=MarketObservation(
                surface=IntelligenceSurface.BLOG,
                market="Decatur, IL",
                source_name=f"Competitor {index}",
                source_url=f"https://example{index}.com/blog/owner-financing",
                headline_or_topic="Flexible owner financing",
                hook="Flexible terms",
            ),
            measured_channel_actions={"blog": "Keep Running"},
            observed_at=now,
            now=now,
        )
        ledger = result.ledger
    assert result.challenger_tests
    candidate = result.challenger_tests[0]
    assert "challenger" in candidate.recommendation.casefold()
    assert "scale" in candidate.evidence_rule.casefold()
    assert candidate.measured_channel_decision == "Keep Running"


def test_measured_pause_cannot_be_overridden_by_competitor_research() -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    ledger = MarketingIntelligenceLedger()
    for index in range(2):
        result = process_collected_observation(
            ledger,
            source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
            observation=MarketObservation(
                surface=IntelligenceSurface.BLOG,
                market="Peoria, IL",
                source_name=f"Competitor {index}",
                source_url=f"https://competitor{index}.com/blog",
                headline_or_topic="Buy with flexible terms",
                hook="Low move-in options",
            ),
            measured_channel_actions={"blog": "Pause Spend"},
            observed_at=now,
            now=now,
        )
        ledger = result.ledger
    assert result.challenger_tests
    assert "hold" in result.challenger_tests[0].recommendation.casefold()
    assert result.challenger_tests[0].measured_channel_decision == "Pause Spend"


class FakeStore:
    def __init__(self) -> None:
        self.ledger = MarketingIntelligenceLedger()
        self.saved = False

    def load(self) -> MarketingIntelligenceLedger:
        return self.ledger

    def save(self, ledger: MarketingIntelligenceLedger) -> None:
        self.ledger = ledger
        self.saved = True


def test_process_and_save_persists_private_ledger_result() -> None:
    store = FakeStore()
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    result = process_and_save_collected_observation(
        store,
        source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
        observation=observation(),
        measured_channel_actions={"blog": "Collect More Data"},
        observed_at=now,
        now=now,
    )
    assert store.saved is True
    assert store.ledger == result.ledger
    assert len(store.ledger.observations) == 1


def test_public_google_surface_stays_non_automatic() -> None:
    with pytest.raises(MarketingIntelligenceIngestionError, match="not permitted"):
        process_collected_observation(
            MarketingIntelligenceLedger(),
            source=ResearchSource.GOOGLE_ADS_TRANSPARENCY,
            observation=MarketObservation(
                surface=IntelligenceSurface.GOOGLE_ADS,
                market="Decatur, IL",
                source_name="Google Ads Transparency",
                headline_or_topic="Observed ad pattern",
            ),
            measured_channel_actions={"google_ads": "Collect More Data"},
        )
