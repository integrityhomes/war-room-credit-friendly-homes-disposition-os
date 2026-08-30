from __future__ import annotations

from cfh_disposition.marketing_intelligence import IntelligenceSurface, MarketObservation
from cfh_disposition.marketing_intelligence_store import MarketingIntelligenceLedger
from cfh_disposition.marketing_research_config import (
    CompetitorResearchTarget,
    MarketingResearchConfig,
)
from cfh_disposition.marketing_research_runtime import (
    run_and_persist_public_competitor_research,
    run_public_competitor_research,
)


def target(name: str, url: str, *, enabled: bool = True) -> CompetitorResearchTarget:
    return CompetitorResearchTarget(
        source_name=name,
        market="Decatur, IL",
        url=url,
        enabled=enabled,
    )


def observation_for(url: str, name: str) -> MarketObservation:
    return MarketObservation(
        surface=IntelligenceSurface.BLOG,
        market="Decatur, IL",
        source_name=name,
        source_url=url,
        headline_or_topic="Flexible owner financing",
        hook="Flexible terms",
    )


def test_empty_configuration_is_clean_noop() -> None:
    result = run_public_competitor_research(
        config=MarketingResearchConfig(),
        ledger=MarketingIntelligenceLedger(),
        measured_channel_actions={},
        collector=lambda **kwargs: observation_for(kwargs["url"], kwargs["source_name"]),
    )
    assert result.attempted_targets == 0
    assert result.collected_targets == 0
    assert result.failed_targets == 0
    assert result.intelligence is None


def test_disabled_targets_are_not_attempted() -> None:
    calls: list[str] = []

    def collector(**kwargs):  # noqa: ANN003, ANN202
        calls.append(kwargs["url"])
        return observation_for(kwargs["url"], kwargs["source_name"])

    result = run_public_competitor_research(
        config=MarketingResearchConfig(
            targets=[
                target("Enabled", "https://enabled.example/blog"),
                target("Disabled", "https://disabled.example/blog", enabled=False),
            ]
        ),
        ledger=MarketingIntelligenceLedger(),
        measured_channel_actions={"blog": "Keep Running"},
        collector=collector,
    )
    assert result.configured_targets == 2
    assert result.attempted_targets == 1
    assert calls == ["https://enabled.example/blog"]


def test_one_failed_site_does_not_stop_successful_target() -> None:
    def collector(**kwargs):  # noqa: ANN003, ANN202
        if "blocked" in kwargs["url"]:
            raise RuntimeError("robots policy blocked collection")
        return observation_for(kwargs["url"], kwargs["source_name"])

    result = run_public_competitor_research(
        config=MarketingResearchConfig(
            targets=[
                target("Blocked", "https://blocked.example/page"),
                target("Good", "https://good.example/blog"),
            ]
        ),
        ledger=MarketingIntelligenceLedger(),
        measured_channel_actions={"blog": "Keep Running"},
        collector=collector,
    )
    assert result.attempted_targets == 2
    assert result.collected_targets == 1
    assert result.failed_targets == 1
    assert [item.status for item in result.target_results] == ["failed", "collected"]
    assert result.intelligence is not None
    assert len(result.intelligence.ledger.observations) == 1


class FakeConfigStore:
    def __init__(self, config: MarketingResearchConfig) -> None:
        self.config = config

    def load(self) -> MarketingResearchConfig:
        return self.config


class FakeIntelligenceStore:
    def __init__(self) -> None:
        self.ledger = MarketingIntelligenceLedger()
        self.save_count = 0

    def load(self) -> MarketingIntelligenceLedger:
        return self.ledger

    def save(self, ledger: MarketingIntelligenceLedger) -> None:
        self.ledger = ledger
        self.save_count += 1


def test_successful_batch_persists_once() -> None:
    intelligence_store = FakeIntelligenceStore()
    result = run_and_persist_public_competitor_research(
        config_store=FakeConfigStore(
            MarketingResearchConfig(
                targets=[
                    target("One", "https://one.example/blog"),
                    target("Two", "https://two.example/blog"),
                ]
            )
        ),
        intelligence_store=intelligence_store,
        measured_channel_actions={"blog": "Collect More Data"},
        collector=lambda **kwargs: observation_for(kwargs["url"], kwargs["source_name"]),
    )
    assert result.collected_targets == 2
    assert intelligence_store.save_count == 1
    assert len(intelligence_store.ledger.observations) == 2


def test_no_external_action_fields_exist_on_runtime_result() -> None:
    result = run_public_competitor_research(
        config=MarketingResearchConfig(targets=[target("One", "https://one.example/blog")]),
        ledger=MarketingIntelligenceLedger(),
        measured_channel_actions={"blog": "Pause Spend"},
        collector=lambda **kwargs: observation_for(kwargs["url"], kwargs["source_name"]),
    )
    assert not hasattr(result, "spend")
    assert not hasattr(result, "publish")
    assert not hasattr(result, "send")
