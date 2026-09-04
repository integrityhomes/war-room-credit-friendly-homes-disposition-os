import json
import sys
from types import SimpleNamespace

import pytest

from cfh_disposition.google_property_readonly_loader import (
    V14_PROPERTY_COLUMNS,
    build_read_only_google_credentials,
    build_read_only_google_runtime,
    list_read_only_worksheet_names,
    make_read_only_sheet_loader,
)
from cfh_disposition.google_property_runtime_bridge import (
    APPROVED_READ_ONLY_SCOPES,
    GoogleBridgeError,
    run_read_only_property_source_test,
)

PRIVATE_MARKER = "PRIVATE-MATERIAL-MUST-NOT-LEAK"


class FakeCredentials:
    def __init__(self, scopes: list[str]) -> None:
        self.scopes = scopes


class FakeWorksheet:
    def __init__(self, title: str, rows: list[list[object]]) -> None:
        self.title = title
        self.rows = rows
        self.ranges: list[str] = []

    def get(self, source_range: str) -> list[list[object]]:
        self.ranges.append(source_range)
        return self.rows


class FakeSpreadsheet:
    def __init__(self, worksheets: list[FakeWorksheet]) -> None:
        self._worksheets = worksheets

    def worksheets(self) -> list[FakeWorksheet]:
        return self._worksheets


def source_row(address: str) -> list[object]:
    values = {name: "" for name in V14_PROPERTY_COLUMNS}
    values.update(
        property_address=address,
        status="Available",
        sales_price="$150,000",
        down_payment="$10,000",
        total_monthly_payment="$1,250",
        last_update="2026-09-04T11:00:00Z",
        lockbox_code="DO-NOT-DISPLAY",
        seller_email="private@example.invalid",
        notes="private note",
    )
    return [values[name] for name in V14_PROPERTY_COLUMNS]


def install_fakes(monkeypatch: pytest.MonkeyPatch, worksheets: list[FakeWorksheet]) -> None:
    credentials_type = SimpleNamespace(
        from_service_account_info=lambda _payload, scopes: FakeCredentials(scopes)
    )
    monkeypatch.setitem(
        sys.modules,
        "google.oauth2.service_account",
        SimpleNamespace(Credentials=credentials_type),
    )
    spreadsheet = FakeSpreadsheet(worksheets)
    monkeypatch.setitem(
        sys.modules,
        "gspread",
        SimpleNamespace(
            authorize=lambda _credentials: SimpleNamespace(
                open_by_key=lambda _sheet_id: spreadsheet
            )
        ),
    )


def secrets() -> dict[str, str]:
    return {
        "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(
            {
                "type": "service_account",
                "client_email": "fixture@example.invalid",
                "private_key": PRIVATE_MARKER,
            }
        ),
        "GOOGLE_SHEET_ID": "fictional-sheet-reference",
    }


def test_credentials_use_only_exact_read_only_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fakes(monkeypatch, [])
    credentials = build_read_only_google_credentials(
        {"type": "service_account"}, APPROVED_READ_ONLY_SCOPES
    )
    assert tuple(credentials.scopes) == APPROVED_READ_ONLY_SCOPES
    with pytest.raises(GoogleBridgeError, match="exactly the approved read-only scopes"):
        build_read_only_google_credentials(
            {"type": "service_account"},
            ("https://www.googleapis.com/auth/spreadsheets",),
        )


def test_lists_worksheets_and_requires_one_explicit_match(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fakes(monkeypatch, [FakeWorksheet("Decatur", []), FakeWorksheet("Quincy", [])])
    assert list_read_only_worksheet_names(object(), "fixture") == ("Decatur", "Quincy")
    with pytest.raises(GoogleBridgeError, match="missing or ambiguous"):
        make_read_only_sheet_loader("Missing")(object(), "fixture", 3)


def test_bounded_loader_routes_three_rows_through_existing_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    worksheet = FakeWorksheet(
        "Decatur",
        [
            list(V14_PROPERTY_COLUMNS),
            source_row("101 Example Avenue, Decatur, IL 62521"),
            source_row("102 Example Avenue, Decatur, IL 62521"),
            source_row("103 Example Avenue, Decatur, IL 62521"),
        ],
    )
    install_fakes(monkeypatch, [worksheet])
    factory, loader = build_read_only_google_runtime("Decatur")
    result = run_read_only_property_source_test(
        secrets=secrets(), credential_factory=factory, sheet_loader=loader
    )
    assert result.rows_read == result.rows_displayed == 3
    assert worksheet.ranges == ["A1:AB4"]
    assert result.google_writes == result.commandcore_persistence == 0
    assert result.external_actions_started is False
    serialized = result.model_dump_json()
    assert PRIVATE_MARKER not in serialized
    for sensitive in ("DO-NOT-DISPLAY", "private@example.invalid", "private note"):
        assert sensitive not in serialized
    assert all(item.canonical_identity for item in result.previews)
    assert all(item.normalization_result == "Valid" for item in result.previews)


def test_duplicate_identity_is_detected_without_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = source_row("101 Example Avenue, Decatur, IL 62521")
    install_fakes(monkeypatch, [FakeWorksheet("Decatur", [duplicate, duplicate])])
    factory, loader = build_read_only_google_runtime("Decatur")
    result = run_read_only_property_source_test(
        secrets=secrets(), credential_factory=factory, sheet_loader=loader
    )
    assert [item.duplicate_result for item in result.previews] == ["Duplicate", "Duplicate"]
    assert result.commandcore_persistence == 0


def test_errors_are_sanitized_and_no_write_surface_is_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    def unsafe_authorize(_credentials: object) -> object:
        raise RuntimeError(PRIVATE_MARKER)

    monkeypatch.setitem(sys.modules, "gspread", SimpleNamespace(authorize=unsafe_authorize))
    with pytest.raises(GoogleBridgeError) as raised:
        list_read_only_worksheet_names(object(), PRIVATE_MARKER)
    assert PRIVATE_MARKER not in str(raised.value)
    loader = make_read_only_sheet_loader("Decatur")
    assert not any(hasattr(loader, name) for name in ("update", "append_row", "delete_rows", "add_worksheet"))


def test_missing_sheet_and_excess_rows_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "gspread",
        SimpleNamespace(authorize=lambda _credentials: SimpleNamespace(open_by_key=lambda _sheet_id: (_ for _ in ()).throw(RuntimeError(PRIVATE_MARKER)))),
    )
    with pytest.raises(GoogleBridgeError, match="could not be opened") as missing:
        make_read_only_sheet_loader("Decatur")(object(), "missing", 3)
    assert PRIVATE_MARKER not in str(missing.value)

    rows = [source_row(f"{number} Example Avenue, Decatur, IL 62521") for number in range(101, 105)]
    install_fakes(monkeypatch, [FakeWorksheet("Decatur", rows)])
    with pytest.raises(GoogleBridgeError, match="three-row safety limit"):
        make_read_only_sheet_loader("Decatur")(object(), "fixture", 3)
