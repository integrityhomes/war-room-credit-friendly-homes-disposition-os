import json
import logging
import socket
from collections.abc import Mapping
from typing import Any

import pytest

from cfh_disposition.google_property_runtime_bridge import (
    APPROVED_READ_ONLY_SCOPES,
    FIRST_LIVE_TEST_ROW_LIMIT,
    GoogleBridgeError,
    ReadOnlySourceBatch,
    run_read_only_property_source_test,
)
from cfh_disposition.google_property_source_adapter import V14PropertySourceType

SECRET_MARKER = "NEVER-LOG-PRIVATE-KEY-MATERIAL"
SHEET_MARKER = "private-sheet-id"


def secrets(**updates: object) -> dict[str, object]:
    values: dict[str, object] = {
        "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(
            {"type": "service_account", "client_email": "fixture@example.invalid", "private_key": SECRET_MARKER}
        ),
        "GOOGLE_SHEET_ID": SHEET_MARKER,
    }
    values.update(updates)
    return values


def row(number: int = 1, **updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "sheet_row": number,
        "property_address": f"{100 + number} Example Avenue, Springfield, MO 65801",
        "status": "Available",
        "sales_price": 150000 + number,
        "down_payment": 10000,
        "total_monthly_payment": 1250,
        "last_update": "2026-09-04T11:00:00Z",
        "lockbox_code": "DO-NOT-DISPLAY",
        "seller_email": "private@example.invalid",
        "notes": "private note",
    }
    value.update(updates)
    return value


def credential_factory(payload: Mapping[str, Any], scopes: tuple[str, ...]) -> object:
    assert payload["private_key"] == SECRET_MARKER
    assert scopes == APPROVED_READ_ONLY_SCOPES
    return object()


def loader(rows: tuple[Mapping[str, Any], ...]):
    def load(_credentials: object, sheet_id: str, limit: int) -> ReadOnlySourceBatch:
        assert sheet_id == SHEET_MARKER
        assert limit == FIRST_LIVE_TEST_ROW_LIMIT
        return ReadOnlySourceBatch(
            source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET,
            tab_name="Properties",
            rows=rows,
        )

    return load


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: pytest.fail("No network allowed"))


def test_bridge_routes_three_rows_through_adapter_with_safe_preview_only() -> None:
    result = run_read_only_property_source_test(
        secrets=secrets(),
        credential_factory=credential_factory,
        sheet_loader=loader(tuple(row(index) for index in range(1, 4))),
    )
    assert result.rows_read == result.rows_displayed == 3
    assert result.google_writes == result.commandcore_persistence == 0
    assert result.external_actions_started is False
    first = result.previews[0]
    assert first.property_address == "101 Example Avenue, Springfield, MO 65801"
    assert first.canonical_identity
    assert first.normalization_result == "Valid"
    assert first.duplicate_result == "New Property"
    serialized = result.model_dump_json()
    for forbidden in (SECRET_MARKER, SHEET_MARKER, "DO-NOT-DISPLAY", "private@example.invalid", "private note"):
        assert forbidden not in serialized


def test_identity_is_deterministic_and_duplicate_batch_is_reported() -> None:
    source = (row(), row(2, property_address=row()["property_address"]))
    first = run_read_only_property_source_test(
        secrets=secrets(), credential_factory=credential_factory, sheet_loader=loader(source)
    )
    second = run_read_only_property_source_test(
        secrets=secrets(), credential_factory=credential_factory, sheet_loader=loader(source)
    )
    assert [item.canonical_identity for item in first.previews] == [item.canonical_identity for item in second.previews]
    assert [item.duplicate_result for item in first.previews] == ["Duplicate", "Duplicate"]


@pytest.mark.parametrize("missing", ["GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEET_ID"])
def test_missing_secret_fails_without_disclosing_other_values(missing: str) -> None:
    configured = secrets()
    del configured[missing]
    with pytest.raises(GoogleBridgeError) as raised:
        run_read_only_property_source_test(
            secrets=configured, credential_factory=credential_factory, sheet_loader=loader((row(),))
        )
    assert SECRET_MARKER not in str(raised.value)
    assert SHEET_MARKER not in str(raised.value)


def test_malformed_secret_and_provider_error_are_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(GoogleBridgeError) as malformed:
        run_read_only_property_source_test(
            secrets=secrets(GOOGLE_SERVICE_ACCOUNT_JSON=SECRET_MARKER),
            credential_factory=credential_factory,
            sheet_loader=loader((row(),)),
        )
    assert SECRET_MARKER not in str(malformed.value)

    def unsafe_error(_payload: Mapping[str, Any], _scopes: tuple[str, ...]) -> object:
        raise RuntimeError(SECRET_MARKER)

    with pytest.raises(GoogleBridgeError) as provider:
        run_read_only_property_source_test(
            secrets=secrets(), credential_factory=unsafe_error, sheet_loader=loader((row(),))
        )
    assert SECRET_MARKER not in str(provider.value)
    assert SECRET_MARKER not in caplog.text
    assert not logging.getLogger().handlers or SECRET_MARKER not in caplog.text


def test_non_read_only_scope_and_write_mode_fail_before_loader() -> None:
    called = False

    def should_not_load(_credentials: object, _sheet_id: str, _limit: int) -> ReadOnlySourceBatch:
        nonlocal called
        called = True
        return loader(())(_credentials, _sheet_id, _limit)

    with pytest.raises(GoogleBridgeError, match="exactly the approved read-only scopes"):
        run_read_only_property_source_test(
            secrets=secrets(),
            credential_factory=credential_factory,
            sheet_loader=should_not_load,
            scopes=("https://www.googleapis.com/auth/spreadsheets",),
        )
    with pytest.raises(GoogleBridgeError, match="read-only test mode"):
        run_read_only_property_source_test(
            secrets=secrets(), credential_factory=credential_factory, sheet_loader=should_not_load, mode="write"  # type: ignore[arg-type]
        )
    assert called is False


def test_more_than_three_rows_and_ambiguous_source_fail_closed() -> None:
    with pytest.raises(GoogleBridgeError, match="three-row safety limit"):
        run_read_only_property_source_test(
            secrets=secrets(), credential_factory=credential_factory, sheet_loader=loader(tuple(row(i) for i in range(1, 5)))
        )
    ambiguous = lambda *_args: ReadOnlySourceBatch(  # noqa: E731
        source_type=V14PropertySourceType.DIRECT_GOOGLE_SHEET, tab_name=" ", rows=(row(),)
    )
    with pytest.raises(GoogleBridgeError, match="ambiguous"):
        run_read_only_property_source_test(
            secrets=secrets(), credential_factory=credential_factory, sheet_loader=ambiguous
        )
