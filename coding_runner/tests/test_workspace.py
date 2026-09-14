from __future__ import annotations

from pathlib import Path

import pytest

from runner.workspace import Workspace


def test_workspace_reads_and_writes_only_inside_root(tmp_path: Path) -> None:
    workspace = Workspace.open(tmp_path)
    path = workspace.write_text("safe/file.txt", "ok")

    assert path == tmp_path / "safe" / "file.txt"
    assert workspace.read_text("safe/file.txt") == "ok"


def test_workspace_refuses_path_escape(tmp_path: Path) -> None:
    workspace = Workspace.open(tmp_path)

    with pytest.raises(PermissionError, match="escapes"):
        workspace.resolve_inside("../outside.txt")
