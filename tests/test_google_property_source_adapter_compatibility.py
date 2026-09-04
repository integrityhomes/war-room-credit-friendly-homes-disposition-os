import json
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cfh_disposition.commandcore_property_inventory import (
    SyncResultState,
    plan_inventory_sync,
    plan_property_sync,
)
from cfh_disposition.google_property_source_adapter import (
    V14PropertySourceContext,
    V14PropertySourceType,
    adapt_v14_property_row,
)
from cfh_disposition.google_sheet_property_rows import RowValidationState

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def _rows(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _context(source_type: V14PropertySourceType) -> V14PropertySourceContext:
    return V14PropertySourceContext(
        source_type=source_type,
        source_reference="fictional-source-reference",
        tab_name="Properties",
    )


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Compatibility tests must not access Google or any network service")

    monkeypatch.setattr(socket, "create_connection", denied)


def test_direct_sheet_shape_maps_into_canonical_inventory() -> None:
    source = _rows("v14_direct_sheet_property_rows.json")[0]
    normalized = adapt_v14_property_row(
        source,
        context=_context(V14PropertySourceType.DIRECT_GOOGLE_SHEET),
    )
    assert normalized.state is RowValidationState.VALID
    row = normalized.normalized
    assert row is not None
    assert row.source_type == "Direct Google Sheet"
    assert row.source_tab == "Properties"
    assert row.source_reference_hash
    assert row.source_reference_hash != "fictional-source-reference"
    assert row.source_row_number == 9
    assert row.address == "123 Example Avenue"
    assert row.total_price == Decimal("150000")
    assert row.monthly_payment == Decimal("1250")
    assert row.legal_description == "Fictional legal description"
    assert row.parcel_number == "TEST-PARCEL-001"

    planned = plan_property_sync(normalized, [], synced_at=NOW)
    assert planned.state is SyncResultState.NEW_PROPERTY
    assert planned.record is not None
    assert planned.record.source_type == "Direct Google Sheet"
    assert planned.record.source_tab == "Properties"
    assert planned.record.source_row_number == 9


def test_drive_xlsx_shape_has_equivalent_identity_and_mapping() -> None:
    direct_source = _rows("v14_direct_sheet_property_rows.json")[0]
    xlsx_source = _rows("v14_drive_xlsx_property_rows.json")[0]
    direct = adapt_v14_property_row(
        direct_source,
        context=_context(V14PropertySourceType.DIRECT_GOOGLE_SHEET),
    )
    xlsx = adapt_v14_property_row(
        xlsx_source,
        context=_context(V14PropertySourceType.DRIVE_XLSX),
    )
    assert direct.normalized is not None
    assert xlsx.normalized is not None
    assert direct.normalized.source_record_id == xlsx.normalized.source_record_id
    assert direct.normalized.total_price == xlsx.normalized.total_price == Decimal("150000")
    assert xlsx.normalized.source_type == "Google Drive XLSX"
    assert xlsx.normalized.source_row_number == 41

    direct_plan = plan_property_sync(direct, [], synced_at=NOW)
    xlsx_plan = plan_property_sync(xlsx, [], synced_at=NOW)
    assert direct_plan.commandcore_property_id == xlsx_plan.commandcore_property_id

    duplicate_batch = plan_inventory_sync([direct, xlsx], [], synced_at=NOW)
    assert [item.state for item in duplicate_batch] == [SyncResultState.DUPLICATE] * 2


def test_blank_xlsx_values_do_not_erase_verified_values_or_assignment() -> None:
    direct_source = _rows("v14_direct_sheet_property_rows.json")[0]
    initial = plan_property_sync(
        adapt_v14_property_row(
            direct_source,
            context=_context(V14PropertySourceType.DIRECT_GOOGLE_SHEET),
        ),
        [],
        synced_at=NOW,
    )
    assert initial.record is not None
    existing = initial.record.model_copy(
        update={"assigned_worker_or_team": "Existing Worker", "lockbox_code": "VERIFIED-LOCKBOX"}
    )
    xlsx_source = _rows("v14_drive_xlsx_property_rows.json")[0]
    updated = plan_property_sync(
        adapt_v14_property_row(
            xlsx_source,
            context=_context(V14PropertySourceType.DRIVE_XLSX),
        ),
        [existing],
        synced_at=NOW + timedelta(hours=1),
    )
    assert updated.record is not None
    assert updated.record.commandcore_property_id == existing.commandcore_property_id
    assert updated.record.assigned_worker_or_team == "Existing Worker"
    assert updated.record.lockbox_code == "VERIFIED-LOCKBOX"
    assert updated.record.notes == "Fictional direct-Sheet test row"


@pytest.mark.parametrize(
    ("fixture_name", "source_type"),
    [
        ("v14_direct_sheet_property_rows.json", V14PropertySourceType.DIRECT_GOOGLE_SHEET),
        ("v14_drive_xlsx_property_rows.json", V14PropertySourceType.DRIVE_XLSX),
    ],
)
def test_malformed_or_ambiguous_rows_fail_closed(
    fixture_name: str,
    source_type: V14PropertySourceType,
) -> None:
    malformed = _rows(fixture_name)[1]
    result = adapt_v14_property_row(malformed, context=_context(source_type))
    assert result.normalized is None
    assert result.state in {
        RowValidationState.MISSING_REQUIRED_INFORMATION,
        RowValidationState.INVALID_SOURCE_ROW,
    }
    planned = plan_property_sync(result, [], synced_at=NOW)
    assert planned.record is None
    assert planned.state in {
        SyncResultState.MISSING_REQUIRED_INFORMATION,
        SyncResultState.INVALID_SOURCE_ROW,
    }
