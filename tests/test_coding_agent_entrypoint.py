from __future__ import annotations

from pathlib import Path

from cfh_disposition.coding_agent import build_ticket, write_ticket
from cfh_disposition.command_agent import dispatch_command


def test_coding_agent_builds_deterministic_dev_ticket_with_no_crm_or_production_authority(tmp_path: Path) -> None:
    first = build_ticket("Fix the contract builder regression")
    second = build_ticket("  Fix   the contract builder regression  ")

    assert first.ticket_id == second.ticket_id
    assert first.branch_name == second.branch_name
    assert first.status == "planned"
    assert "crm.commit" in first.forbidden_actions
    assert "merge_main" in first.forbidden_actions
    assert "deploy_edge_function" in first.forbidden_actions
    assert "run_ruff" in first.allowed_actions
    assert "run_pytest" in first.allowed_actions
    assert "draft_pull_request" in first.allowed_actions

    path = write_ticket(first, tmp_path / "ticket.json")
    assert path.exists()
    assert first.ticket_id in path.read_text(encoding="utf-8")


def test_command_center_dev_request_never_starts_coding_agent() -> None:
    result = dispatch_command(
        command="Fix the Python code and open a pull request",
        deal={"id": "FIXTURE-DEAL"},
    )

    assert result.status == "needs_you"
    assert result.needs_you == "That belongs to the Dev team."
    assert result.task_agent_runs == ()


def test_coding_agent_has_no_command_center_or_crm_dependency() -> None:
    source = Path("src/cfh_disposition/coding_agent.py").read_text(encoding="utf-8")

    assert "command_agent" not in source
    assert "task_agent" not in source
    assert "supabase" not in source.lower()
    assert "commandcore-crm-core" not in source
    assert "SideEffectBus" not in source
