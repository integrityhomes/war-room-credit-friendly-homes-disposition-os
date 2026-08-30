from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .marketing_intelligence import MarketObservation
from .marketing_intelligence_collection_pipeline import (
    IntelligenceCollectionResult,
    process_collected_observation,
)
from .marketing_intelligence_sources import ResearchSource
from .marketing_intelligence_store import MarketingIntelligenceLedger
from .marketing_research_config import CompetitorResearchTarget, MarketingResearchConfig
from .public_competitor_collector import collect_public_competitor_page


@dataclass(frozen=True, slots=True)
class ResearchTargetResult:
    source_name: str
    url: str
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MarketingResearchRunResult:
    configured_targets: int
    attempted_targets: int
    collected_targets: int
    failed_targets: int
    target_results: tuple[ResearchTargetResult, ...]
    intelligence: IntelligenceCollectionResult | None


Collector = Callable[..., MarketObservation]


def _collect_target(target: CompetitorResearchTarget, collector: Collector) -> MarketObservation:
    return collector(
        url=str(target.url),
        market=target.market,
        source_name=target.source_name,
    )


def run_public_competitor_research(
    *,
    config: MarketingResearchConfig,
    ledger: MarketingIntelligenceLedger,
    measured_channel_actions: Mapping[str, str],
    collector: Collector = collect_public_competitor_page,
) -> MarketingResearchRunResult:
    """Run enabled public competitor targets without letting one failure stop the batch."""

    enabled = config.enabled_targets
    if not enabled:
        return MarketingResearchRunResult(
            configured_targets=len(config.targets),
            attempted_targets=0,
            collected_targets=0,
            failed_targets=0,
            target_results=(),
            intelligence=None,
        )

    working_ledger = ledger
    latest: IntelligenceCollectionResult | None = None
    results: list[ResearchTargetResult] = []
    collected = 0

    for target in enabled:
        try:
            observation = _collect_target(target, collector)
            latest = process_collected_observation(
                working_ledger,
                source=ResearchSource.PUBLIC_COMPETITOR_WEBSITE,
                observation=observation,
                measured_channel_actions=measured_channel_actions,
            )
            working_ledger = latest.ledger
        except Exception as exc:
            results.append(
                ResearchTargetResult(
                    source_name=target.source_name,
                    url=str(target.url),
                    status="failed",
                    detail=str(exc)[:300],
                )
            )
            continue
        collected += 1
        results.append(
            ResearchTargetResult(
                source_name=target.source_name,
                url=str(target.url),
                status="collected",
            )
        )

    return MarketingResearchRunResult(
        configured_targets=len(config.targets),
        attempted_targets=len(enabled),
        collected_targets=collected,
        failed_targets=len(enabled) - collected,
        target_results=tuple(results),
        intelligence=latest,
    )


def run_and_persist_public_competitor_research(
    *,
    config_store: Any,
    intelligence_store: Any,
    measured_channel_actions: Mapping[str, str],
    collector: Collector = collect_public_competitor_page,
) -> MarketingResearchRunResult:
    """Load private configuration/ledger, run the batch, and save successful research."""

    config = config_store.load()
    ledger = intelligence_store.load()
    result = run_public_competitor_research(
        config=config,
        ledger=ledger,
        measured_channel_actions=measured_channel_actions,
        collector=collector,
    )
    if result.intelligence is not None:
        intelligence_store.save(result.intelligence.ledger)
    return result
