from __future__ import annotations

import pytest

from cfh_disposition.harness.mode import HarnessMode
from cfh_disposition.task_agent import run_task_agent


DEAL = {
    "id": "FIXTURE-DEAL-TASK-1",
    "internal_only": True,
    "external_action_started": False,
}


def test_task_agent_simulation_behavior_and_deterministic_run_id_are_preserved() -> None:
    first = run_task_agent(
        deal=DEAL,
        work_type="follow_up",
        command="Prepare internal follow-up task",
    )
    second = run_task_agent(
        deal=DEAL,
        work_type="follow_up",
        command="  prepare   INTERNAL follow-up TASK  ",
        mode=HarnessMode.SIMULATION,
    )

    assert first.status == "simulated"
    assert first.mode == "simulation"
    assert first.run_id == second.run_id
    assert first.deal_id == DEAL["id"]
    assert first.task_preview["links"]["deal_id"] == DEAL["id"]
    assert first.task_preview["coordination_status"] == "simulation"
    assert first.task_preview["internal_only"] is True
    assert first.task_preview["external_action_started"] is False
    assert first.external_action_started is False
    assert len(first.side_effects) == 1
    assert first.side_effects[0]["action_type"] == "crm.commit"
    assert first.side_effects[0]["decision"] == "blocked"


def test_task_agent_stages_exactly_one_intended_internal_crm_task() -> None:
    staging_calls: list[tuple[str, dict]] = []
    production_calls: list[tuple[str, dict]] = []

    result = run_task_agent(
        deal=DEAL,
        work_type="follow_up",
        command="Prepare internal follow-up task",
        mode=HarnessMode.STAGING,
        staging_executor=lambda action, payload: staging_calls.append((action, payload)),
        production_executor=lambda action, payload: production_calls.append((action, payload)),
    )
    simulation = run_task_agent(
        deal=DEAL,
        work_type="follow_up",
        command="Prepare internal follow-up task",
    )

    assert result.status == "staged"
    assert result.mode == "staging"
    assert result.run_id == simulation.run_id
    assert result.deal_id == DEAL["id"]
    assert result.internal_only is True
    assert result.external_action_started is False
    assert len(result.side_effects) == 1
    assert result.side_effects[0]["action_type"] == "crm.commit"
    assert result.side_effects[0]["decision"] == "staging_only"
    assert len(staging_calls) == 1
    assert production_calls == []

    action, payload = staging_calls[0]
    task = payload["record"]
    assert action == "crm.commit"
    assert payload["entity"] == "tasks"
    assert task == result.task_preview
    assert task["external_id"] == result.run_id
    assert task["links"]["deal_id"] == DEAL["id"]
    assert task["internal_only"] is True
    assert task["external_action_started"] is False
    assert task["approval_bypassed"] is False
    assert {item["action_type"] for item in result.side_effects} == {"crm.commit"}


def test_task_agent_rejects_production_before_any_executor_call() -> None:
    staging_calls: list[tuple[str, dict]] = []
    production_calls: list[tuple[str, dict]] = []

    with pytest.raises(ValueError, match="does not support production mode"):
        run_task_agent(
            deal=DEAL,
            work_type="follow_up",
            command="Prepare internal follow-up task",
            mode=HarnessMode.PRODUCTION,
            staging_executor=lambda action, payload: staging_calls.append((action, payload)),
            production_executor=lambda action, payload: production_calls.append((action, payload)),
        )

    assert staging_calls == []
    assert production_calls == []
