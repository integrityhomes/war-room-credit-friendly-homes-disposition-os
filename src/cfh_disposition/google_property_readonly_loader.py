"""Executable read-only Google loader compatible with the V14 CFD Builder source."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any

try:
    from google.oauth2.service_account import Credentials
except ImportError:  # pragma: no cover - exercised through the fail-closed factory
    Credentials = None  # type: ignore[assignment,misc]

from .google_property_runtime_bridge import (
    APPROVED_READ_ONLY_SCOPES,
    FIRST_LIVE_TEST_ROW_LIMIT,
    GoogleBridgeError,
    ReadOnlySheetLoader,
    ReadOnlySourceBatch,
)
from .google_property_source_adapter import V14PropertySourceType

V14_PROPERTY_COLUMNS = (
    "property_address",
    "lockbox_code",
    "beds",
    "baths",
    "square_feet",
    "down_payment",
    "total_monthly_payment",
    "sales_price",
    "interest_rate",
    "monthly_principal_interest",
    "monthly_insurance",
    "monthly_taxes",
    "insurance_included",
    "photo_link",
    "legal_description",
    "parcel_number",
    "last_tax_bill",
    "fair_cash_value",
    "assessed_value",
    "lender",
    "payment_system",
    "seller_entity",
    "seller_address",
    "seller_state",
    "seller_email",
    "notes",
    "date_added",
    "last_update",
)

FULL_AUDIT_BATCH_SIZE = 500


class ReadOnlyWorksheetValues(tuple):
    """One worksheet's populated values, retained only for in-memory normalization."""

    tab_name: str

    def __new__(cls, tab_name: str, values: Sequence[Sequence[object]]):
        instance = super().__new__(cls, tuple(tuple(row) for row in values))
        instance.tab_name = tab_name
        return instance


def build_read_only_google_credentials(
    payload: Mapping[str, Any], scopes: tuple[str, ...]
) -> object:
    """Create CFD Builder-style credentials with only the approved scopes."""
    if scopes != APPROVED_READ_ONLY_SCOPES:
        raise GoogleBridgeError("Google credentials require exactly the approved read-only scopes.")
    if Credentials is None:
        raise GoogleBridgeError("Read-only Google credentials could not be created safely.")
    try:
        return Credentials.from_service_account_info(
            dict(payload), scopes=list(APPROVED_READ_ONLY_SCOPES)
        )
    except Exception:
        raise GoogleBridgeError("Read-only Google credentials could not be created safely.") from None


def _open_spreadsheet(credentials: object, sheet_id: str) -> object:
    try:
        gspread = importlib.import_module("gspread")
        return gspread.authorize(credentials).open_by_key(sheet_id)
    except Exception:
        raise GoogleBridgeError("The configured read-only Google spreadsheet could not be opened.") from None


def list_read_only_worksheet_names(credentials: object, sheet_id: str) -> tuple[str, ...]:
    """List worksheet titles without reading cells or exposing source identifiers."""
    spreadsheet = _open_spreadsheet(credentials, sheet_id)
    try:
        names = tuple(str(item.title).strip() for item in spreadsheet.worksheets())
    except Exception:
        raise GoogleBridgeError("Worksheet names could not be listed safely.") from None
    if not names or any(not name for name in names):
        raise GoogleBridgeError("The spreadsheet has no unambiguous worksheet names.")
    folded = [name.casefold() for name in names]
    if len(set(folded)) != len(folded):
        raise GoogleBridgeError("The spreadsheet has ambiguous worksheet names.")
    return names


def _parsed_v14_row(values: Sequence[object], sheet_row_number: int) -> dict[str, object]:
    mapped = {
        column: values[index] if index < len(values) else None
        for index, column in enumerate(V14_PROPERTY_COLUMNS)
    }
    mapped["sheet_row"] = sheet_row_number
    return mapped


def _is_qualifying_row(values: Sequence[object]) -> bool:
    if not values:
        return False
    address = str(values[0] or "").strip()
    return bool(address and address.casefold() not in {"address", "property address", "property_address"})


def make_read_only_sheet_loader(worksheet_name: str) -> ReadOnlySheetLoader:
    """Bind one explicit worksheet to the bridge's bounded read-only loader contract."""
    approved_name = worksheet_name.strip()
    if not approved_name:
        raise GoogleBridgeError("An explicit worksheet name is required.")

    def load(credentials: object, sheet_id: str, limit: int) -> ReadOnlySourceBatch:
        if limit != FIRST_LIVE_TEST_ROW_LIMIT:
            raise GoogleBridgeError("The Google property read is limited to exactly three rows.")
        spreadsheet = _open_spreadsheet(credentials, sheet_id)
        try:
            worksheets = tuple(spreadsheet.worksheets())
            matches = [item for item in worksheets if str(item.title).strip().casefold() == approved_name.casefold()]
            if len(matches) != 1:
                raise GoogleBridgeError("The requested worksheet is missing or ambiguous.")
            # Four physical rows permit one conventional header plus at most three property rows.
            values = matches[0].get("A1:AB4")
        except GoogleBridgeError:
            raise
        except Exception:
            raise GoogleBridgeError("The requested worksheet could not be read safely.") from None
        rows = tuple(
            _parsed_v14_row(row, index)
            for index, row in enumerate(values, start=1)
            if _is_qualifying_row(row)
        )
        if len(rows) > FIRST_LIVE_TEST_ROW_LIMIT:
            raise GoogleBridgeError("The worksheet returned more than the three-row safety limit.")
        return ReadOnlySourceBatch(
            source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET,
            tab_name=str(matches[0].title).strip(),
            rows=rows,
        )

    return load


def build_read_only_google_runtime(worksheet_name: str) -> tuple[Callable[..., object], ReadOnlySheetLoader]:
    """Return the two executable dependencies accepted by the existing runtime bridge."""
    return build_read_only_google_credentials, make_read_only_sheet_loader(worksheet_name)


def load_all_read_only_worksheet_values(
    credentials: object, sheet_id: str
) -> tuple[ReadOnlyWorksheetValues, ...]:
    """Discover every worksheet and read populated values without exposing writes."""
    spreadsheet = _open_spreadsheet(credentials, sheet_id)
    try:
        worksheets = tuple(spreadsheet.worksheets())
        names = tuple(str(item.title).strip() for item in worksheets)
        if not names or any(not name for name in names):
            raise GoogleBridgeError("The spreadsheet has no unambiguous worksheet names.")
        if len({name.casefold() for name in names}) != len(names):
            raise GoogleBridgeError("The spreadsheet has ambiguous worksheet names.")
        return tuple(
            ReadOnlyWorksheetValues(name, worksheet.get_all_values())
            for name, worksheet in zip(names, worksheets, strict=True)
        )
    except GoogleBridgeError:
        raise
    except Exception:
        raise GoogleBridgeError(
            "The configured property worksheets could not be read safely."
        ) from None
