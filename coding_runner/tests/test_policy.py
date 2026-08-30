from __future__ import annotations

from runner.policy import check_action, check_branch, check_control_file_edit


def test_protected_branches_are_refused() -> None:
    assert check_branch("main").allowed is False
    assert check_branch("master").allowed is False
    assert check_branch("feature/test-runner").allowed is True


def test_consequential_actions_are_denied_in_phase_one() -> None:
    for action in (
        "production_deploy",
        "production_crm_write",
        "email_send",
        "sms_send",
        "contract_sign",
        "ads_spend",
        "money_move",
        "privilege_escalation",
    ):
        assert check_action(action).allowed is False


def test_runner_cannot_change_its_control_files_without_owner_approval() -> None:
    denied = check_control_file_edit("coding_runner/src/runner/policy.py")
    approved = check_control_file_edit("coding_runner/src/runner/policy.py", owner_approved=True)
    normal = check_control_file_edit("coding_runner/src/runner/report.py")

    assert denied.allowed is False
    assert approved.allowed is True
    assert normal.allowed is True
