from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .harness.mode import HarnessMode
from .harness.side_effects import ActionType, SideEffectBus


@dataclass(frozen=True, slots=True)
class TaskAgentRun:
    run_id: str
    deal_id: str
    work_type: str
    command_text: str
    mode: str
    internal_only: bool
    external_action_started: bool
    task_preview: dict[str, Any]
    side_effects: list[dict[str, Any]]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_command(command: str) -> str:
    return " ".join(command.strip().lower().split())


def _run_id(deal_id: str, work_type: str, command: str) -> str:
    digest = hashlib.sha256(
        f"{deal_id}|{work_type}|{_normalized_command(command)}".encode()
    ).hexdigest()[:24]
    return f"task-agent-{deal_id}-{work_type}-{digest}"


def run_task_agent(
    *,
    deal: dict[str, Any],
    work_type: str,
    command: str,
    mode: HarnessMode = HarnessMode.SIMULATION,
) -> TaskAgentRun:
    """Prepare exactly one internal task in simulation without writing production CRM."""
    if mode is not HarnessMode.SIMULATION:
        raise ValueError("The Command Center Task Agent is simulation-only in this slice.")

    deal_id = _text(deal.get("id"))
    if not deal_id:
        raise ValueError("A Deal ID is required before dispatching Task Agent work.")

    timestamp = datetime.now(UTC).isoformat()
    task = {
        "external_id": _run_id(deal_id, work_type, command),
        "task_type": "deal_lifecycle_request",
        "work_type": work_type,
        "title": f"Simulated {work_type.replace('_', ' ')} work",
        "status": "open",
        "source": "commandcore-task-agent",
        "command_text": command,
        "normalized_command": _normalized_command(command),
        "requested_at": timestamp,
        "coordination_status": "simulation",
        "internal_only": True,
        "external_action_started": False,
        "approval_bypassed": False,
        "links": {"deal_id": deal_id},
    }

    simulation_deal = {
        **deal,
        "internal_only": True,
        "external_action_started": False,
    }
    bus = SideEffectBus(HarnessMode.SIMULATION)
    record = bus.request(
        ActionType.CRM_COMMIT,
        {"entity": "tasks", "record": task},
        deal=simulation_deal,
    )
    status = "simulated" if record.decision == "blocked" and bus.provider_calls == 0 else "failed"
    return TaskAgentRun(
        run_id=task["external_id"],
        deal_id=deal_id,
        work_type=work_type,
        command_text=command,
        mode=HarnessMode.SIMULATION.value,
        internal_only=True,
        external_action_started=False,
        task_preview=task,
        side_effects=[item.to_dict() for item in bus.records],
        status=status,
    )
