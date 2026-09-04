from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunReport:
    goal: str
    workspace: str
    branch: str
    files_changed: tuple[str, ...]
    commands_run: tuple[str, ...]
    tests_passed: bool
    blocked_actions: tuple[str, ...]
    approval_required: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_report(report: RunReport, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return destination
