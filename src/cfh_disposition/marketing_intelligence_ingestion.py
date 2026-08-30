from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .marketing_intelligence import MarketObservation
from .marketing_intelligence_sources import ResearchSource, can_collect_automatically
from .marketing_intelligence_store import MarketingIntelligenceLedger, upsert_observation


class MarketingIntelligenceIngestionError(ValueError):
    """Raised when a research observation cannot be accepted safely."""


@dataclass(frozen=True, slots=True)
class ObservationEnvelope:
    source: ResearchSource
    observation: MarketObservation
    account_authorized: bool = False


def ingest_observation(
    ledger: MarketingIntelligenceLedger,
    envelope: ObservationEnvelope,
    *,
    observed_at: datetime | None = None,
) -> MarketingIntelligenceLedger:
    """Accept an automatically collected observation only when source policy permits it."""

    if not can_collect_automatically(
        envelope.source,
        authorized=envelope.account_authorized,
    ):
        raise MarketingIntelligenceIngestionError(
            f"Automatic collection is not permitted for source: {envelope.source.value}."
        )
    return upsert_observation(
        ledger,
        envelope.observation,
        observed_at=observed_at,
    )
