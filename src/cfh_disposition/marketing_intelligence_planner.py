from __future__ import annotations

from dataclasses import dataclass

from .marketing_intelligence import IntelligenceSurface
from .marketing_intelligence_optimizer import IntelligenceTestCandidate


@dataclass(frozen=True, slots=True)
class PlannerImprovementBrief:
    surface: IntelligenceSurface
    market: str
    channel_key: str | None
    objective: str
    test_angle: str
    measured_decision: str
    recommended_action: str
    requires_owner_approval: bool
    can_publish_automatically: bool
    copy_source_text: bool


PAID_SURFACES = {
    IntelligenceSurface.GOOGLE_ADS,
    IntelligenceSurface.META_ADS,
    IntelligenceSurface.CHATGPT_ADS,
}

APPROVAL_GATED_CONTENT_SURFACES = {
    IntelligenceSurface.BLOG,
    IntelligenceSurface.EMAIL,
    IntelligenceSurface.SMS,
    IntelligenceSurface.SOCIAL,
}


def build_planner_improvement_briefs(
    candidates: list[IntelligenceTestCandidate],
) -> list[PlannerImprovementBrief]:
    briefs: list[PlannerImprovementBrief] = []
    for candidate in candidates:
        paid = candidate.surface in PAID_SURFACES
        approval_gated = candidate.surface in APPROVAL_GATED_CONTENT_SURFACES
        briefs.append(
            PlannerImprovementBrief(
                surface=candidate.surface,
                market=candidate.market,
                channel_key=candidate.channel_key,
                objective=(
                    "Create an original challenger that tests the observed market pattern against CommandCore's current control."
                ),
                test_angle=candidate.commandcore_test,
                measured_decision=candidate.measured_channel_decision,
                recommended_action=candidate.recommendation,
                requires_owner_approval=paid,
                can_publish_automatically=not paid and not approval_gated,
                copy_source_text=False,
            )
        )
    return briefs
