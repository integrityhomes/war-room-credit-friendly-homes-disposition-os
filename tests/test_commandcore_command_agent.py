from __future__ import annotations

from cfh_disposition.command_agent import dispatch_command


def _deal() -> dict[str, object]:
    return {
        "id": "FIXTURE-DEAL-HARRIS-0001",
        "title": "123 Harris St",
        "internal_only": True,
        "external_action_started": False,
    }


def test_ops_command_dispatches_exactly_one_task_agent_in_simulation() -> None:
    result = dispatch_command(command="Prepare an offer for 123 Harris St", deal=_deal())

    assert result.status == "simulated"
    assert result.intent == "prepare_offer"
    assert result.needs_you is None
    assert len(result.task_agent_runs) == 1

    run = result.task_agent_runs[0]
    assert run.mode == "simulation"
    assert run.internal_only is True
    assert run.external_action_started is False
    assert run.status == "simulated"
    assert len(run.side_effects) == 1
    assert run.side_effects[0]["action_type"] == "crm.commit"
    assert run.side_effects[0]["decision"] == "blocked"
    assert "Simulation mode" in run.side_effects[0]["reason"]


def test_dev_command_never_dispatches_task_agent_or_coding_agent() -> None:
    result = dispatch_command(command="Fix the GitHub code and open a pull request", deal=_deal())

    assert result.status == "needs_you"
    assert result.needs_you == "That belongs to the Dev team."
    assert result.task_agent_runs == ()


def test_unclear_command_asks_for_one_ops_choice_and_dispatches_nothing() -> None:
    result = dispatch_command(command="Handle Harris St", deal=_deal())

    assert result.status == "needs_you"
    assert result.needs_you is not None
    assert result.task_agent_runs == ()


def test_ops_command_without_deal_stops_before_dispatch() -> None:
    result = dispatch_command(command="Prepare the contract", deal=None)

    assert result.status == "needs_you"
    assert result.intent == "prepare_contract"
    assert result.task_agent_runs == ()
