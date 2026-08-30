from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class JourneyReadinessSummary:
    total: int
    healthy: int
    failed: int
    rows: tuple[dict[str, str], ...]

    @property
    def label(self) -> str:
        return f"{self.healthy}/{self.total} healthy"


def journey_readiness_summary(payload: dict[str, Any]) -> JourneyReadinessSummary:
    raw = payload.get("journeys")
    journeys = raw if isinstance(raw, list) else []
    rows: list[dict[str, str]] = []
    for item in journeys:
        if not isinstance(item, dict):
            continue
        name = str(item.get("journey") or "Unknown journey").strip()
        healthy = item.get("healthy") is True
        failed_services = item.get("failed_services")
        failures = [str(value) for value in failed_services] if isinstance(failed_services, list) else []
        rows.append(
            {
                "Journey": name,
                "Status": "Healthy" if healthy else "Needs attention",
                "Problem": ", ".join(failures) if failures else "",
            }
        )

    healthy_count = sum(row["Status"] == "Healthy" for row in rows)
    return JourneyReadinessSummary(
        total=len(rows),
        healthy=healthy_count,
        failed=len(rows) - healthy_count,
        rows=tuple(rows),
    )
