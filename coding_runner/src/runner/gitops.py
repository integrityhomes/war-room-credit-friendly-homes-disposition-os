from __future__ import annotations

import subprocess
from pathlib import Path

from .policy import check_branch


def current_branch(repo_root: str | Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=Path(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def require_feature_branch(repo_root: str | Path) -> str:
    branch = current_branch(repo_root)
    decision = check_branch(branch)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    return branch


def git_diff(repo_root: str | Path) -> str:
    require_feature_branch(repo_root)
    result = subprocess.run(
        ["git", "diff", "--"],
        cwd=Path(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
