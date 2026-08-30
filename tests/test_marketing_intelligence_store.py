from datetime import UTC, datetime

from cfh_disposition.marketing_intelligence import IntelligenceSurface, MarketObservation
from cfh_disposition.marketing_intelligence_store import (
    MarketingIntelligenceLedger,
    observation_identity,
    upsert_observation,
)


def observation(headline: str = "Owner financing with low down payment") -> MarketObservation:
    return MarketObservation(
        surface=IntelligenceSurface.BLOG,
        market="Decatur",
        source_name="Example Competitor",
        source_url="https://example.com/blog/owner-financing",
        headline_or_topic=headline,
        hook="Lead with flexible path to homeownership",
        call_to_action="View available homes",
        keyword_or_intent="owner financing homes decatur il",
    )


def test_repeated_observation_is_deduped_and_counted() -> None:
    first_seen = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    second_seen = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    ledger = upsert_observation(
        MarketingIntelligenceLedger(),
        observation(),
        observed_at=first_seen,
    )
    ledger = upsert_observation(ledger, observation(), observed_at=second_seen)

    assert len(ledger.observations) == 1
    stored = ledger.observations[0]
    assert stored.sightings == 2
    assert stored.first_seen_at == first_seen
    assert stored.last_seen_at == second_seen


def test_different_headline_creates_distinct_learning_record() -> None:
    ledger = upsert_observation(MarketingIntelligenceLedger(), observation())
    ledger = upsert_observation(
        ledger,
        observation("How owner financing works for buyers"),
    )

    assert len(ledger.observations) == 2


def test_identity_normalizes_market_and_headline_case() -> None:
    first = observation()
    second = first.model_copy(
        update={
            "market": "  DECATUR  ",
            "headline_or_topic": " OWNER   FINANCING WITH LOW DOWN PAYMENT ",
        }
    )

    assert observation_identity(first) == observation_identity(second)
