import pytest

from cfh_disposition.marketing_intelligence import IntelligenceSurface, MarketObservation
from cfh_disposition.marketing_intelligence_ingestion import (
    MarketingIntelligenceIngestionError,
    ObservationEnvelope,
    ingest_observation,
)
from cfh_disposition.marketing_intelligence_sources import ResearchSource
from cfh_disposition.marketing_intelligence_store import MarketingIntelligenceLedger


def observation() -> MarketObservation:
    return MarketObservation(
        surface=IntelligenceSurface.BLOG,
        market="Decatur",
        source_name="Competitor",
        source_url="https://example.com/blog",
        headline_or_topic="Owner financing with low down payment",
    )


def test_public_competitor_site_observation_can_be_ingested() -> None:
    ledger = ingest_observation(
        MarketingIntelligenceLedger(),
        ObservationEnvelope(
            source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
            observation=observation(),
        ),
    )

    assert len(ledger.observations) == 1


def test_google_search_scrape_observation_is_rejected() -> None:
    with pytest.raises(MarketingIntelligenceIngestionError):
        ingest_observation(
            MarketingIntelligenceLedger(),
            ObservationEnvelope(
                source=ResearchSource.GOOGLE_SEARCH_RESULTS,
                observation=observation(),
            ),
        )


def test_owned_google_api_data_requires_authorization() -> None:
    envelope = ObservationEnvelope(
        source=ResearchSource.GOOGLE_ADS_OWN_ACCOUNT,
        observation=observation(),
    )
    with pytest.raises(MarketingIntelligenceIngestionError):
        ingest_observation(MarketingIntelligenceLedger(), envelope)

    accepted = ingest_observation(
        MarketingIntelligenceLedger(),
        ObservationEnvelope(
            source=ResearchSource.GOOGLE_ADS_OWN_ACCOUNT,
            observation=observation(),
            account_authorized=True,
        ),
    )
    assert len(accepted.observations) == 1
