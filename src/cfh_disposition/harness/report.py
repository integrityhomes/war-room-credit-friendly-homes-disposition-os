from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .side_effects import SideEffectRecord


@dataclass(slots=True)
class HarnessReport:
    scenario: str
    mode: str
    fixture_family: str
    verdict: str
    provider_calls: int
    actions: list[SideEffectRecord] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        action_dicts = [action.to_dict() for action in self.actions]
        return {
            "harness": "CommandCore Test & Simulation Harness",
            "scenario": self.scenario,
            "mode": self.mode,
            "fixture_family": self.fixture_family,
            "verdict": self.verdict,
            "provider_calls": self.provider_calls,
            "intended_actions": action_dicts,
            "blocked_actions": [item for item in action_dicts if item["decision"] == "blocked"],
            "approval_required_actions": [item for item in action_dicts if item["approval_required"]],
            "artifacts": self.artifacts,
        }

    def markdown(self) -> str:
        data = self.to_dict()
        lines = [
            "# CommandCore Harness Report",
            "",
            f"- Scenario: `{self.scenario}`",
            f"- Mode: `{self.mode}`",
            f"- Verdict: **{self.verdict}**",
            f"- Provider calls: **{self.provider_calls}**",
            f"- Intended actions: **{len(data['intended_actions'])}**",
            f"- Blocked actions: **{len(data['blocked_actions'])}**",
            "",
            "## Action decisions",
        ]
        for action in self.actions:
            lines.append(f"- `{action.action_type}` → **{action.decision}** — {action.reason}")
        return "\n".join(lines) + "\n"


def write_report(report: HarnessReport, output_dir: str | Path = "artifacts") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "harness-report.json"
    markdown_path = directory / "harness-report.md"
    json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    markdown_path.write_text(report.markdown(), encoding="utf-8")
    return json_path, markdown_path
