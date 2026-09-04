import json
from collections.abc import Mapping
from typing import Any

import pytest

from cfh_disposition.google_property_full_audit import run_full_property_source_audit
from cfh_disposition.google_property_readonly_loader import (
    V14_PROPERTY_COLUMNS,
    ReadOnlyWorksheetValues,
    load_all_read_only_worksheet_values,
)
from cfh_disposition.google_property_runtime_bridge import (
    APPROVED_READ_ONLY_SCOPES,
    GoogleBridgeError,
)

SECRET_MARKER = "PRIVATE-CREDENTIAL-MUST-NOT-LEAK"


def secrets() -> dict[str, str]:
    return {
        "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(
            {
                "type": "service_account",
                "client_email": "fixture@example.invalid",
                "private_key": SECRET_MARKER,
            }
        ),
        "GOOGLE_SHEET_ID": "fictional-sheet-reference",
    }


def credentials(payload: Mapping[str, Any], scopes: tuple[str, ...]) -> object:
    assert payload["private_key"] == SECRET_MARKER
    assert scopes == APPROVED_READ_ONLY_SCOPES
    return object()


def fixed_row(address: str, **updates: object) -> list[object]:
    row = {name: "" for name in V14_PROPERTY_COLUMNS}
    row.update(
        property_address=address,
        sales_price="150000",
        down_payment="10000",
        total_monthly_payment="1250",
        lockbox_code="DO-NOT-DISPLAY",
        seller_email="private@example.invalid",
        notes="private notes",
    )
    row.update(updates)
    return [row[name] for name in V14_PROPERTY_COLUMNS]


def test_full_audit_discovers_tabs_classifies_restrictive_tabs_and_deduplicates() -> None:
    address = "101 Example Avenue, Decatur, IL 62521"
    worksheets = (
        ReadOnlyWorksheetValues(
            "Decatur/Quincy",
            [
                ["Inventory title"],
                [],
                list(V14_PROPERTY_COLUMNS),
                fixed_row(address),
                fixed_row("102 Example Avenue, Decatur, IL 62521"),
            ],
        ),
        ReadOnlyWorksheetValues("SOLD", [fixed_row(address)]),
        ReadOnlyWorksheetValues(
            "DO NOT SELL LIST",
            [fixed_row("103 Example Avenue, Decatur, IL 62521")],
        ),
        ReadOnlyWorksheetValues(
            "Future Unknown Market",
            [fixed_row("104 Example Avenue, Decatur, IL 62521")],
        ),
    )

    result = run_full_property_source_audit(
        secrets(),
        credential_factory=credentials,
        worksheet_loader=lambda *_args: worksheets,
    )

    assert result.worksheets_discovered == result.worksheets_processed == 4
    assert result.total_physical_rows_inspected == 8
    assert result.normalized_properties == 5
    assert result.duplicate_candidates == 2
    assert result.sold_count == 1
    assert result.do_not_sell_count == 1
    assert result.active_available_count == 0
    assert result.google_writes == result.commandcore_persistence == 0
    statuses = {item.worksheet_or_tab: item.status for item in result.safe_previews}
    assert statuses["SOLD"] == "Sold / Unavailable"
    assert statuses["DO NOT SELL LIST"] == "Paused"
    assert statuses["Future Unknown Market"] == "Coming Soon"
    assert result.safe_previews[0].canonical_identity == result.safe_previews[2].canonical_identity
    serialized = result.model_dump_json()
    for sensitive in (
        SECRET_MARKER,
        "DO-NOT-DISPLAY",
        "private@example.invalid",
        "private notes",
        "fictional-sheet-reference",
    ):
        assert sensitive not in serialized


def test_variable_header_location_blank_rows_malformed_rows_and_large_batch() -> None:
    header = ["Property Address", "Sales Price", "Down Payment", "Monthly Payment"]
    values = [["Report heading"], [], header]
    values.extend(
        [
            [f"{number} Example Street, Springfield, IL 62701", "160000", "12000", "1300"]
            for number in range(1000, 2005)
        ]
    )
    values.append(["not a complete property address"])
    result = run_full_property_source_audit(
        secrets(),
        credential_factory=credentials,
        worksheet_loader=lambda *_args: (
            ReadOnlyWorksheetValues("Springfield/New Athens", values),
        ),
    )

    assert result.total_physical_rows_inspected == 1009
    assert result.normalized_properties == 1005
    assert result.malformed_or_skipped_rows == 4
    assert result.properties_by_source_tab[0].valid_property_rows == 1005


def test_loader_discovers_every_worksheet_and_sanitizes_provider_failure() -> None:
    class Worksheet:
        def __init__(self, title: str) -> None:
            self.title = title

        def get_all_values(self) -> list[list[str]]:
            return [["Property Address"], ["101 Example Avenue, Decatur, IL 62521"]]

    class Spreadsheet:
        def worksheets(self) -> list[Worksheet]:
            return [Worksheet("One"), Worksheet("Future")]

    import sys
    from types import SimpleNamespace

    original = sys.modules.get("gspread")
    sys.modules["gspread"] = SimpleNamespace(
        authorize=lambda _credentials: SimpleNamespace(
            open_by_key=lambda _sheet_id: Spreadsheet()
        )
    )
    try:
        batches = load_all_read_only_worksheet_values(object(), "fictional")
        assert [item.tab_name for item in batches] == ["One", "Future"]
    finally:
        if original is None:
            del sys.modules["gspread"]
        else:
            sys.modules["gspread"] = original

    def failure(*_args: object) -> tuple[ReadOnlyWorksheetValues, ...]:
        raise RuntimeError(SECRET_MARKER)

    with pytest.raises(GoogleBridgeError) as raised:
        run_full_property_source_audit(
            secrets(), credential_factory=credentials, worksheet_loader=failure
        )
    assert SECRET_MARKER not in str(raised.value)
