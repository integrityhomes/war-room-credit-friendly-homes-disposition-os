from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path

    @classmethod
    def open(cls, root: str | Path) -> "Workspace":
        resolved = Path(root).expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Workspace does not exist or is not a directory: {resolved}")
        return cls(root=resolved)

    def resolve_inside(self, relative_path: str | Path) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("Path escapes the approved workspace root.") from exc
        return candidate

    def read_text(self, relative_path: str | Path) -> str:
        return self.resolve_inside(relative_path).read_text(encoding="utf-8")

    def write_text(self, relative_path: str | Path, content: str) -> Path:
        destination = self.resolve_inside(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination
