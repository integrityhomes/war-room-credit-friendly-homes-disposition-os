from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

PROTECTED_BRANCHES = {"main", "master"}
PROTECTED_CONTROL_PATHS = {
    "coding_runner/src/runner/policy.py",
    "coding_runner/src/runner/workspace.py",
    "coding_runner/src/runner/gitops.py",
    "coding_runner/STATE.md",
}
DENIED_ACTIONS = {
    "production_deploy",
    "production_crm_write",
    "email_send",
    "sms_send",
    "contract_sign",
    "offer_send",
    "ads_spend",
    "money_move",
    "paid_service_create",
    "privilege_escalation",
    "public_exposure",
    "production_secret_change",
}


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str


def check_branch(branch: str) -> PolicyDecision:
    normalized = branch.strip().casefold()
    if normalized in PROTECTED_BRANCHES:
        return PolicyDecision(False, f"Development work is refused on protected branch {branch!r}.")
    if not normalized:
        return PolicyDecision(False, "A feature branch is required.")
    return PolicyDecision(True, "Feature branch is allowed.")


def check_action(action: str) -> PolicyDecision:
    if action.strip().casefold() in DENIED_ACTIONS:
        return PolicyDecision(False, f"Action {action!r} is outside Phase 1 authority.")
    return PolicyDecision(True, "Action is not denied by the Phase 1 policy.")


def check_control_file_edit(path: str, *, owner_approved: bool = False) -> PolicyDecision:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix().lstrip("./")
    if normalized in PROTECTED_CONTROL_PATHS and not owner_approved:
        return PolicyDecision(False, "Runner control files require explicit owner approval to modify.")
    return PolicyDecision(True, "Path is allowed by the control-file policy.")
