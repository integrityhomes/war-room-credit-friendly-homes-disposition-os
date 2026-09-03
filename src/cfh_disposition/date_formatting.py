"""Cross-platform date formatting helpers."""

from typing import Any


def portable_strftime(value: Any, format_string: str) -> str:
    """Format a date while preserving POSIX no-padding directives on Windows."""
    try:
        return value.strftime(format_string)
    except ValueError:
        if "%-" not in format_string:
            raise
        return value.strftime(format_string.replace("%-", "%#"))
