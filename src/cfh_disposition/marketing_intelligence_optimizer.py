from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from .marketing_intelligence import IntelligenceBrief, IntelligenceSurface


SURFACE_CHANNEL_KEYS: dict[IntelligenceSurface, str] = {
    IntelligenceSurface.GOOGLE_ADS: "google_ads",
    IntelligenceSurface.META_ADS: "meta_ads",
    IntelligenceSurface.CHATGPT_ADS: "chatgpt_ads",
    IntelligenceSurface.BLOG: "blog",
    IntelligenceSurface.MARKET_SEO: "market_seo",
    IntelligenceSurface.EMAIL: "email",
    IntelligenceSurface.SMS: "sms",
    IntelligenceSurface.LANDING_PAGE: "property_page",
}


class IntelligenceTestCandidate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    surface: IntelligenceSurface
    channel_key: str | None = None
    market: str
    observed_pattern: str
    occurrences: int = Field(ge=2)
    measured_channel_decision: str
    recommendation: str
    commandcore_test: str
    evidence_rule: str


def build_market_informed_tests(
    brief: IntelligenceBrief,
    measured_channel_actions: Mapping[str, str],
) -> list[IntelligenceTestCandidate]:
    """Combine observable market patterns with CommandCore's measured decisions.

    External research may propose a challenger, but it never upgrades a measured
    decision to Scale and never overrides Pause/Repair safety signals.
    """

    candidates: list[IntelligenceTestCandidate] = []
    for pattern in brief.patterns:
        channel_key = SURFACE_CHANNEL_KEYS.get(pattern.surface)
        measured = measured_channel_actions.get(channel_key or "", "No measured decision")
        measured_normalized = measured.casefold()

        if "pause" in measured_normalized:
            recommendation = "Hold research test until the measured spend/funnel issue is resolved."
        elif "repair" in measured_normalized:
            recommendation = "Use this pattern only as a repair-test idea; do not increase spend or volume."
        else:
            recommendation = "Use this as a controlled challenger test, not as evidence to scale."

        candidates.append(
            IntelligenceTestCandidate(
                surface=pattern.surface,
                channel_key=channel_key,
                market=pattern.market,
                observed_pattern=pattern.pattern,
                occurrences=pattern.occurrences,
                measured_channel_decision=measured,
                recommendation=recommendation,
                commandcore_test=pattern.commandcore_test,
                evidence_rule=(
                    "Competitor/ranking visibility is research evidence only. Scale, keep, pause, or repair "
                    "decisions must come from CommandCore's own tracked results and approved spend data."
                ),
            )
        )
    return candidates
