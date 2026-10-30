"""Classify pull-request paths that must not auto-merge.

Used by `.github/workflows/commandcore-safe-auto-merge.yml`. The workflow must
run this script from the *base* branch checkout only — never from PR head.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import PurePosixPath

# Keep this list in sync with docs/SAFE_AUTO_MERGE.md and AGENTS.md owner-approval rules.
SENSITIVE_GLOBS: tuple[str, ...] = (
    ".github/**",
    "AGENTS.md",
    "docs/PRODUCT_VISION.md",
    "database/**",
    "supabase/**",
    "**/migrations/**",
    "src/cfh_disposition/auth*.py",
    "src/cfh_disposition/app_secrets.py",
    "**/*secret*",
    "**/*credential*",
    ".env*",
    ".streamlit/**",
    "requirements*.txt",
    "pyproject.toml",
)

SENSITIVE_NAME_SUBSTRINGS: tuple[str, ...] = (
    "contract",
    "payment",
    "money",
    "bank",
    "billing",
    "compliance",
    "legal",
    "signing",
    "offer_engine",
)


def _normalize(path: str) -> str:
    normalized = path.replace("\\", "/")
    # Only strip a leading "./" prefix; keep leading dots on ".github" / ".env".
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized

def _matches_glob(path: str, pattern: str) -> bool:
    """Match git-style path globs against a normalized repo-relative path."""
    path = _normalize(path)
    pattern = pattern.replace("\\", "/")

    if fnmatch.fnmatchcase(path, pattern):
        return True

    # `**/foo` should also match `foo` at repo root.
    if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
        return True

    # `dir/**` should match files under dir/ (fnmatch needs explicit segments).
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        if path == prefix or path.startswith(prefix + "/"):
            return True

    # `auth*.py` style basename patterns already covered by fnmatch on full path
    # when pattern includes directories; also try basename-only patterns.
    name = PurePosixPath(path).name
    if "/" not in pattern.rstrip("/") and fnmatch.fnmatchcase(name, pattern):
        return True

    return False


def is_sensitive(paths: list[str] | tuple[str, ...]) -> list[str]:
    """Return the subset of ``paths`` that require owner approval (no auto-merge)."""
    hits: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = _normalize(str(raw))
        if not path or path in seen:
            continue
        sensitive = False
        for pattern in SENSITIVE_GLOBS:
            if _matches_glob(path, pattern):
                sensitive = True
                break
        if not sensitive:
            name_lower = PurePosixPath(path).name.lower()
            for needle in SENSITIVE_NAME_SUBSTRINGS:
                if needle in name_lower:
                    sensitive = True
                    break
        if sensitive:
            hits.append(path)
            seen.add(path)
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Changed file paths (repo-relative). Reads stdin lines if omitted.",
    )
    args = parser.parse_args(argv)
    paths = list(args.paths)
    if not paths and not sys.stdin.isatty():
        paths = [line.strip() for line in sys.stdin if line.strip()]

    hits = is_sensitive(paths)
    if hits:
        for path in hits:
            print(path)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
