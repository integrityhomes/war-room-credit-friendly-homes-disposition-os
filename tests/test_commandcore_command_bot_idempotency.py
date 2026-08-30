from cfh_disposition.task_agent import run_task_agent


def test_task_agent_uses_stable_request_identity_for_same_command() -> None:
    deal = {"id": "FIXTURE-DEAL-001", "internal_only": True, "external_action_started": False}

    first = run_task_agent(deal=deal, work_type="prepare_offer", command="Prepare offer for Harris St")
    second = run_task_agent(deal=deal, work_type="prepare_offer", command="  prepare   OFFER for Harris St  ")

    assert first.run_id == second.run_id
    assert first.task_preview["external_id"] == second.task_preview["external_id"]
    assert first.internal_only is True
    assert first.external_action_started is False
    assert first.status == "simulated"
    assert second.status == "simulated"
