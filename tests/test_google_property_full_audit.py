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
    assert result.source_property_rows_detected == 5
    assert result.fully_normalized_properties == 5
    assert result.properties_needing_review == 0
    assert result.true_malformed_property_rows == 0
    assert result.non_property_header_blank_rows == 3
    assert result.duplicate_candidates == 2
    assert result.sold_count == 1
    assert result.do_not_sell_count == 1
    assert result.active_available_count == 3
    assert result.google_writes == result.commandcore_persistence == 0
    statuses = {item.worksheet_or_tab: item.status for item in result.safe_previews}
    assert statuses["SOLD"] == "Sold / Unavailable"
    assert statuses["DO NOT SELL LIST"] == "Paused"
    assert statuses["Future Unknown Market"] == "Available"
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
    header = list(V14_PROPERTY_COLUMNS)
    values = [["Report heading"], [], header]
    values.extend(
        [
            fixed_row(f"{number} Example Street, Springfield, IL 62701")
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
    assert result.source_property_rows_detected == 1005
    assert result.fully_normalized_properties == 1005
    assert result.non_property_header_blank_rows == 4
    assert result.properties_by_source_tab[0].fully_normalized == 1005


def test_v14_detection_preserves_street_only_and_invalid_date_for_review() -> None:
    values = [
        ["Property Address"],
        fixed_row(
            "201 Example Avenue, Springfield, IL 62701",
            last_update="09/04/2026",
        ),
        fixed_row("202 Example Avenue", last_update="09/04/2026"),
        fixed_row(
            "203 Example Avenue, Springfield, IL 62701",
            last_update="not-a-date",
        ),
        fixed_row(
            "204 Example Avenue, Springfield, IL 62701",
            beds="not-a-number",
        ),
        ["Descriptive source note"],
        [],
    ]
    result = run_full_property_source_audit(
        secrets(),
        credential_factory=credentials,
        worksheet_loader=lambda *_args: (
            ReadOnlyWorksheetValues("Decatur/Quincy", values),
        ),
    )

    assert result.source_property_rows_detected == 4
    assert result.fully_normalized_properties == 1
    assert result.properties_needing_review == 2
    assert result.true_malformed_property_rows == 1
    assert result.non_property_header_blank_rows == 3
    assert {item.property_address for item in result.needs_review_previews} == {
        "202 Example Avenue",
        "203 Example Avenue, Springfield, IL 62701",
    }
    assert all(item.source_identity for item in result.needs_review_previews)
    assert all(item.status == "Available" for item in result.needs_review_previews)
    invalid_date = next(
        item
        for item in result.needs_review_previews
        if item.property_address.startswith("203 ")
    )
    assert invalid_date.last_update is None
    assert "date format was not recognized" in invalid_date.reasons[0]


def test_do_not_sell_street_only_property_is_detected_before_canonical_review() -> None:
    result = run_full_property_source_audit(
        secrets(),
        credential_factory=credentials,
        worksheet_loader=lambda *_args: (
            ReadOnlyWorksheetValues(
                "DO NOT SELL LIST", [fixed_row("301 Example Avenue")]
            ),
        ),
    )

    assert result.source_property_rows_detected == 1
    assert result.properties_needing_review == 1
    assert result.do_not_sell_count == 1
    assert result.needs_review_previews[0].status == "Paused"


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
