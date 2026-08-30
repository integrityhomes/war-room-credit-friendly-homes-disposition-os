from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .marketing_intelligence import IntelligenceBrief, build_intelligence_brief
from .marketing_intelligence_store import MarketingIntelligenceLedger

DEFAULT_INTELLIGENCE_LOOKBACK_DAYS = 90


def recent_observations(
    ledger: MarketingIntelligenceLedger,
    *,
    now: datetime | None = None,
    lookback_days: int = DEFAULT_INTELLIGENCE_LOOKBACK_DAYS,
) -> list:
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    bounded_days = max(1, min(lookback_days, 365))
    cutoff = timestamp - timedelta(days=bounded_days)
    return [
        item.observation
        for item in ledger.observations
        if item.last_seen_at.astimezone(UTC) >= cutoff
    ]


def build_current_intelligence_brief(
    ledger: MarketingIntelligenceLedger,
    *,
    now: datetime | None = None,
    lookback_days: int = DEFAULT_INTELLIGENCE_LOOKBACK_DAYS,
) -> IntelligenceBrief:
    observations = recent_observations(
        ledger,
        now=now,
        lookback_days=lookback_days,
    )
    brief = build_intelligence_brief(observations)
    if not observations:
        brief.cautions.append(
            "No recent market observations are available. Do not infer current competitor or ranking patterns from stale research."
        )
    return brief
