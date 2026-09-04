import json
from collections.abc import Mapping
from typing import Any

import pytest

from cfh_disposition.commandcore_property_source_diagnostics import (
    PROPERTY_DIAGNOSTIC_WORKSHEET,
    PropertyDiagnosticFailureCategory,
    run_property_source_diagnostic,
    safe_property_diagnostic_failure,
)
from cfh_disposition.google_property_runtime_bridge import (
    APPROVED_READ_ONLY_SCOPES,
    GoogleBridgeError,
    ReadOnlySourceBatch,
)
from cfh_disposition.google_property_source_adapter import V14PropertySourceType

SECRET_MARKER = "PRIVATE-MATERIAL-MUST-NOT-LEAK"


def test_diagnostic_uses_fixed_tab_and_returns_only_safe_zero_write_result() -> None:
    raw_row: dict[str, object] = {
        "sheet_row": 2,
        "property_address": "101 Example Avenue, Decatur, IL 62521",
        "status": "Available",
        "sales_price": "$150,000",
        "down_payment": "$10,000",
        "total_monthly_payment": "$1,250",
        "last_update": "2026-09-04T11:00:00Z",
        "lockbox_code": "DO-NOT-DISPLAY",
        "seller_email": "private@example.invalid",
        "notes": "private note",
    }

    def credential_factory(
        payload: Mapping[str, Any], scopes: tuple[str, ...]
    ) -> object:
        assert payload["private_key"] == SECRET_MARKER
        assert scopes == APPROVED_READ_ONLY_SCOPES
        return object()

    def sheet_loader(
        _credentials: object, _sheet_id: str, limit: int
    ) -> ReadOnlySourceBatch:
        assert limit == 3
        return ReadOnlySourceBatch(
            source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET,
            tab_name=PROPERTY_DIAGNOSTIC_WORKSHEET,
            rows=(raw_row,),
        )

    result = run_property_source_diagnostic(
        {
            "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(
                {
                    "type": "service_account",
                    "client_email": "fixture@example.invalid",
                    "private_key": SECRET_MARKER,
                }
            ),
            "GOOGLE_SHEET_ID": "fictional-sheet-reference",
        },
        credential_factory=credential_factory,
        sheet_loader=sheet_loader,
    )

    assert result.rows_read == result.rows_displayed == 1
    assert result.google_writes == result.commandcore_persistence == 0
    assert result.external_actions_started is False
    preview = result.previews[0]
    assert preview.worksheet_or_tab == PROPERTY_DIAGNOSTIC_WORKSHEET
    assert preview.canonical_identity
    assert preview.normalization_result == "Valid"
    serialized = result.model_dump_json()
    for sensitive in (
        SECRET_MARKER,
        "DO-NOT-DISPLAY",
        "private@example.invalid",
        "private note",
    ):
        assert sensitive not in serialized


def test_diagnostic_fails_closed_for_incomplete_dependencies_or_wrong_tab() -> None:
    with pytest.raises(GoogleBridgeError, match="dependencies are incomplete"):
        run_property_source_diagnostic({}, credential_factory=lambda *_args: object())

    def wrong_tab_loader(
        _credentials: object, _sheet_id: str, _limit: int
    ) -> ReadOnlySourceBatch:
        return ReadOnlySourceBatch(
            source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET,
            tab_name="Another tab",
            rows=(
                {
                    "sheet_row": 2,
                    "property_address": "101 Example Avenue, Decatur, IL 62521",
                    "status": "Available",
                },
            ),
        )

    with pytest.raises(GoogleBridgeError, match="did not match"):
        run_property_source_diagnostic(
            {
                "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(
                    {
                        "type": "service_account",
                        "client_email": "fixture@example.invalid",
                        "private_key": SECRET_MARKER,
                    }
                ),
                "GOOGLE_SHEET_ID": "fictional-sheet-reference",
            },
            credential_factory=lambda *_args: object(),
            sheet_loader=wrong_tab_loader,
        )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Required CommandCore runtime secret is missing: REDACTED.", "MISSING_RUNTIME_SECRET"),
        ("The configured Google service account secret is malformed.", "MALFORMED_SERVICE_ACCOUNT"),
        ("Read-only Google credentials could not be created safely.", "CREDENTIAL_CREATION_FAILED"),
        ("The configured read-only Google spreadsheet could not be opened.", "SPREADSHEET_OPEN_FAILED"),
        ("Worksheet names could not be listed safely.", "WORKSHEET_DISCOVERY_FAILED"),
        ("The configured property worksheets could not be read safely.", "WORKSHEET_READ_FAILED"),
        ("No property worksheets were discovered.", "NO_WORKSHEETS_FOUND"),
        ("The approved worksheet contained no qualifying property rows.", "NO_QUALIFYING_PROPERTIES"),
        ("Property rows could not be normalized safely.", "ROW_NORMALIZATION_FAILED"),
        ("Duplicate-property planning could not be completed safely.", "DUPLICATE_PLANNING_FAILED"),
        ("The property-source diagnostic did not remain read-only.", "READ_ONLY_SAFETY_FAILURE"),
        (SECRET_MARKER, "UNKNOWN_SAFE_FAILURE"),
    ],
)
def test_safe_failure_categories_never_echo_exception_text(
    message: str, expected: str
) -> None:
    failure = safe_property_diagnostic_failure(GoogleBridgeError(message))
    assert failure.category.value == expected
    assert SECRET_MARKER not in failure.model_dump_json()


def test_safe_failure_category_values_match_the_approved_allowlist() -> None:
    assert {item.value for item in PropertyDiagnosticFailureCategory} == {
        "MISSING_RUNTIME_SECRET",
        "MALFORMED_SERVICE_ACCOUNT",
        "CREDENTIAL_CREATION_FAILED",
        "SPREADSHEET_OPEN_FAILED",
        "WORKSHEET_DISCOVERY_FAILED",
        "WORKSHEET_READ_FAILED",
        "NO_WORKSHEETS_FOUND",
        "NO_QUALIFYING_PROPERTIES",
        "ROW_NORMALIZATION_FAILED",
        "DUPLICATE_PLANNING_FAILED",
        "READ_ONLY_SAFETY_FAILURE",
        "UNKNOWN_SAFE_FAILURE",
    }
