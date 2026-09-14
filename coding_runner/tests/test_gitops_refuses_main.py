from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runner.gitops import require_feature_branch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_gitops_refuses_main_and_allows_feature_branch(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "runner@example.invalid")
    _git(tmp_path, "config", "user.name", "Runner Test")
    (tmp_path / "README.md").write_text("fixture", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "fixture")

    with pytest.raises(PermissionError, match="protected branch"):
        require_feature_branch(tmp_path)

    _git(tmp_path, "switch", "-c", "feature/runner-test")
    assert require_feature_branch(tmp_path) == "feature/runner-test"
