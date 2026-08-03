from __future__ import annotations

from pathlib import Path
import re


SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*=\s*[^\s]+"),
)


def scan_text_for_secrets(text: str) -> list[str]:
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(pattern.pattern)
    return findings


def scan_repository(root: Path) -> dict[str, list[str]]:
    findings: dict[str, list[str]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            matches = scan_text_for_secrets(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue
        if matches:
            findings[str(path.relative_to(root))] = matches
    return findings
