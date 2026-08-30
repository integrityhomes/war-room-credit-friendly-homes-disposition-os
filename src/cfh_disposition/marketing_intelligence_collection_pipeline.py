from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .marketing_intelligence import IntelligenceBrief, MarketObservation
from .marketing_intelligence_ingestion import ObservationEnvelope, ingest_observation
from .marketing_intelligence_optimizer import IntelligenceTestCandidate, build_market_informed_tests
from .marketing_intelligence_pipeline import build_current_intelligence_brief
from .marketing_intelligence_sources import ResearchSource
from .marketing_intelligence_store import MarketingIntelligenceLedger


@dataclass(frozen=True, slots=True)
class IntelligenceCollectionResult:
    ledger: MarketingIntelligenceLedger
    brief: IntelligenceBrief
    challenger_tests: tuple[IntelligenceTestCandidate, ...]


def process_collected_observation(
    ledger: MarketingIntelligenceLedger,
    *,
    source: ResearchSource,
    observation: MarketObservation,
    measured_channel_actions: Mapping[str, str],
    account_authorized: bool = False,
    observed_at: datetime | None = None,
    now: datetime | None = None,
) -> IntelligenceCollectionResult:
    """Ingest one permitted observation and rebuild safe market-informed tests.

    External research can suggest challenger tests only. It never changes spend,
    publishing, or the measured channel decision supplied by CommandCore.
    """

    updated = ingest_observation(
        ledger,
        ObservationEnvelope(
            source=source,
            observation=observation,
            account_authorized=account_authorized,
        ),
        observed_at=observed_at,
    )
    brief = build_current_intelligence_brief(updated, now=now or observed_at)
    tests = build_market_informed_tests(brief, measured_channel_actions)
    return IntelligenceCollectionResult(
        ledger=updated,
        brief=brief,
        challenger_tests=tuple(tests),
    )


def process_and_save_collected_observation(
    store: Any,
    *,
    source: ResearchSource,
    observation: MarketObservation,
    measured_channel_actions: Mapping[str, str],
    account_authorized: bool = False,
    observed_at: datetime | None = None,
    now: datetime | None = None,
) -> IntelligenceCollectionResult:
    """Load, ingest, save, and return the refreshed intelligence result."""

    ledger = store.load()
    result = process_collected_observation(
        ledger,
        source=source,
        observation=observation,
        measured_channel_actions=measured_channel_actions,
        account_authorized=account_authorized,
        observed_at=observed_at,
        now=now,
    )
    store.save(result.ledger)
    return result
