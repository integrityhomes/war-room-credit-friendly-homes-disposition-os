from datetime import date
from pathlib import Path

import pytest

from cfh_disposition.date_formatting import portable_strftime


class WindowsStyleDate:
    def __init__(self):
        self.formats = []

    def strftime(self, format_string):
        self.formats.append(format_string)
        if "%-" in format_string:
            raise ValueError("Invalid format string")
        if format_string == "%#m/%#d/%Y":
            return "1/2/2025"
        raise AssertionError(f"Unexpected format: {format_string}")


class AlwaysInvalidDate:
    def strftime(self, format_string):
        raise ValueError("unrelated invalid format")


def test_portable_strftime_retries_posix_no_padding_with_windows_directives():
    value = WindowsStyleDate()

    assert portable_strftime(value, "%-m/%-d/%Y") == "1/2/2025"
    assert value.formats == ["%-m/%-d/%Y", "%#m/%#d/%Y"]


def test_portable_strftime_preserves_existing_business_output():
    assert portable_strftime(date(2025, 1, 2), "%-m/%-d/%Y") == "1/2/2025"


def test_portable_strftime_does_not_mask_unrelated_format_errors():
    with pytest.raises(ValueError, match="unrelated invalid format"):
        portable_strftime(AlwaysInvalidDate(), "%Q")


def test_vulnerable_facebook_and_marketplace_formatters_use_portable_helper():
    root = Path(__file__).parents[1] / "src" / "cfh_disposition"
    modules = ("facebook_groups.py", "marketplace_calendar.py")

    for module in modules:
        source = (root / module).read_text(encoding="utf-8")
        assert "from .date_formatting import portable_strftime" in source
        assert '.strftime("%-' not in source
        assert ".strftime('%-" not in source
