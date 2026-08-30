from __future__ import annotations

from enum import StrEnum


class HarnessMode(StrEnum):
    SIMULATION = "simulation"
    STAGING = "staging"
    PRODUCTION = "production"


def parse_mode(value: str | HarnessMode | None = None) -> HarnessMode:
    """Return an explicit harness mode, defaulting safely to simulation."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return HarnessMode.SIMULATION
    if isinstance(value, HarnessMode):
        return value
    try:
        return HarnessMode(value.strip().casefold())
    except ValueError as exc:
        raise ValueError(f"Unknown harness mode: {value!r}. Use simulation, staging, or production.") from exc
