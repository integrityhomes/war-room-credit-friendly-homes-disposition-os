from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .harness.mode import HarnessMode
from .harness.side_effects import ActionType, Executor, SideEffectBus


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
    staging_executor: Executor | None = None,
    production_executor: Executor | None = None,
) -> TaskAgentRun:
    """Prepare exactly one internal task in simulation or CRM staging."""
    if mode is HarnessMode.PRODUCTION:
        raise ValueError("The Command Center Task Agent does not support production mode.")

    deal_id = _text(deal.get("id"))
    if not deal_id:
        raise ValueError("A Deal ID is required before dispatching Task Agent work.")

    normalized_work_type = _text(work_type)
    if not normalized_work_type:
        raise ValueError("A work type is required before dispatching Task Agent work.")

    timestamp = datetime.now(UTC).isoformat()
    task = {
        "external_id": _run_id(deal_id, normalized_work_type, command),
        "task_type": "deal_lifecycle_request",
        "work_type": normalized_work_type,
        "title": f"{'Simulated' if mode is HarnessMode.SIMULATION else 'Staged'} {normalized_work_type.replace('_', ' ')} work",
        "status": "open",
        "source": "commandcore-task-agent",
        "command_text": command,
        "normalized_command": _normalized_command(command),
        "requested_at": timestamp,
        "coordination_status": mode.value,
        "internal_only": True,
        "external_action_started": False,
        "approval_bypassed": False,
        "links": {"deal_id": deal_id},
    }

    internal_deal = {
        **deal,
        "internal_only": True,
        "external_action_started": False,
    }
    bus = SideEffectBus(
        mode,
        staging_executor=staging_executor,
        production_executor=production_executor,
    )
    record = bus.request(
        ActionType.CRM_COMMIT,
        {"entity": "tasks", "record": task},
        deal=internal_deal,
    )
    if mode is HarnessMode.SIMULATION:
        status = "simulated" if record.decision == "blocked" and bus.provider_calls == 0 else "failed"
    else:
        status = "staged" if record.decision == "staging_only" and bus.provider_calls == 1 else "failed"
    return TaskAgentRun(
        run_id=task["external_id"],
        deal_id=deal_id,
        work_type=normalized_work_type,
        command_text=command,
        mode=mode.value,
        internal_only=True,
        external_action_started=False,
        task_preview=task,
        side_effects=[item.to_dict() for item in bus.records],
        status=status,
    )
