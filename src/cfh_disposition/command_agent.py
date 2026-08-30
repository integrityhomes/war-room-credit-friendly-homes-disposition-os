from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .harness.mode import HarnessMode
from .task_agent import TaskAgentRun, run_task_agent

SUPPORTED_INTENTS = {
    "deal_analysis": "Analyze deal",
    "prepare_offer": "Prepare offer",
    "prepare_contract": "Prepare contract",
    "title_closing": "Title / closing",
    "marketing_dispo": "Marketing / dispo",
}

_DEV_TERMS = (
    "code",
    "coding",
    "github",
    "branch",
    "pull request",
    "pr ",
    "pytest",
    "ruff",
    "deploy",
    "edge function",
    "repository",
    "repo ",
    "bug fix",
    "refactor",
)


@dataclass(frozen=True, slots=True)
class CommandAgentResult:
    status: str
    intent: str | None
    needs_you: str | None
    task_agent_runs: tuple[TaskAgentRun, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["task_agent_runs"] = [run.to_dict() for run in self.task_agent_runs]
        return data


def parse_ops_intent(command: str) -> str | None:
    value = command.lower()
    if any(term in value for term in ("contract", "cfd", "contract for deed", "purchase agreement")):
        return "prepare_contract"
    if any(term in value for term in ("offer", "make an offer", "offer draft")):
        return "prepare_offer"
    if any(term in value for term in ("analyze", "analysis", "underwrite", "comp", "comps")):
        return "deal_analysis"
    if any(term in value for term in ("title", "closing", "close this deal")):
        return "title_closing"
    if any(term in value for term in ("market", "marketing", "dispo", "disposition", "sell this")):
        return "marketing_dispo"
    return None


def is_dev_command(command: str) -> bool:
    normalized = f" {command.strip().lower()} "
    return any(term in normalized for term in _DEV_TERMS)


def dispatch_command(
    *,
    command: str,
    deal: dict[str, Any] | None,
) -> CommandAgentResult:
    """Route one Command Center command to at most one simulation-only Ops Task Agent."""
    if is_dev_command(command):
        return CommandAgentResult(
            status="needs_you",
            intent=None,
            needs_you="That belongs to the Dev team.",
            task_agent_runs=(),
        )

    intent = parse_ops_intent(command)
    if intent is None:
        return CommandAgentResult(
            status="needs_you",
            intent=None,
            needs_you="Tell me whether you want deal analysis, offer prep, contract prep, title/closing, or marketing/dispo work.",
            task_agent_runs=(),
        )
    if not deal:
        return CommandAgentResult(
            status="needs_you",
            intent=intent,
            needs_you="Choose the Deal before I create internal work.",
            task_agent_runs=(),
        )

    run = run_task_agent(
        deal=deal,
        work_type=intent,
        command=command,
        mode=HarnessMode.SIMULATION,
    )
    return CommandAgentResult(
        status="simulated" if run.status == "simulated" else "failed",
        intent=intent,
        needs_you=None,
        task_agent_runs=(run,),
    )
