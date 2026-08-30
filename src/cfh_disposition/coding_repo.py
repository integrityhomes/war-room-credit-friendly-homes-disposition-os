from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_IGNORED_DIRS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "artifacts",
}
_KEY_FILES = {
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "Dockerfile",
    "docker-compose.yml",
    "compose.yml",
    ".env.example",
}


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    root: str
    files: tuple[str, ...]
    key_files: tuple[str, ...]
    python_files: tuple[str, ...]
    test_files: tuple[str, ...]
    docker_files: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_repository(root: str | Path, *, max_files: int = 2000) -> RepositorySnapshot:
    """Inspect one project tree without network access or changing any files."""
    base = Path(root).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {base}")

    discovered: list[str] = []
    for path in sorted(base.rglob("*")):
        if any(part in _IGNORED_DIRS for part in path.relative_to(base).parts):
            continue
        if not path.is_file():
            continue
        discovered.append(path.relative_to(base).as_posix())
        if len(discovered) >= max_files:
            break

    key_files = tuple(path for path in discovered if Path(path).name in _KEY_FILES)
    python_files = tuple(path for path in discovered if path.endswith(".py"))
    test_files = tuple(
        path
        for path in discovered
        if path.endswith(".py") and (Path(path).name.startswith("test_") or "/tests/" in f"/{path}")
    )
    docker_files = tuple(
        path
        for path in discovered
        if Path(path).name in {"Dockerfile", "docker-compose.yml", "compose.yml"}
    )
    return RepositorySnapshot(
        root=str(base),
        files=tuple(discovered),
        key_files=key_files,
        python_files=python_files,
        test_files=test_files,
        docker_files=docker_files,
    )
