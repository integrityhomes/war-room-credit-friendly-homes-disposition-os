from copy import deepcopy
from decimal import Decimal

import pytest

from cfh_disposition.google_sheet_property_rows import (
    CanonicalAvailability,
    RowValidationState,
    normalize_google_sheet_row,
)


def valid_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "Inventory ID": "CFH-ATL-1001",
        "Property Address": "101 Main St",
        "City": "Atlanta",
        "State": "ga",
        "ZIP": "30303",
        "Status": "Ready to Launch",
        "Price": "$125,000",
        "Down": "5,000",
        "Monthly": "1,250",
        "Beds": "3",
        "Baths": "2.5",
        "Updated At": "2026-09-04T12:00:00Z",
    }
    row.update(changes)
    return row


def test_normalizes_aliases_numbers_and_status_without_mutating_source() -> None:
    source = valid_row()
    original = deepcopy(source)
    result = normalize_google_sheet_row(source, source_label="Mock inventory")

    assert result.state is RowValidationState.VALID
    assert result.normalized is not None
    assert result.normalized.availability is CanonicalAvailability.AVAILABLE
    assert result.normalized.state == "GA"
    assert result.normalized.total_price == Decimal("125000")
    assert result.normalized.down_payment == Decimal("5000")
    assert result.normalized.monthly_payment == Decimal("1250")
    assert result.normalized.bedrooms == 3
    assert result.normalized.bathrooms == Decimal("2.5")
    assert len(result.source_row_hash) == 64
    assert source == original


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("available", CanonicalAvailability.AVAILABLE),
        ("pending", CanonicalAvailability.PENDING),
        ("sold", CanonicalAvailability.SOLD_UNAVAILABLE),
        ("unavailable", CanonicalAvailability.SOLD_UNAVAILABLE),
        ("paused", CanonicalAvailability.PAUSED),
        ("coming soon", CanonicalAvailability.COMING_SOON),
        ("draft", CanonicalAvailability.COMING_SOON),
    ],
)
def test_maps_only_approved_availability_states(
    source: str, expected: CanonicalAvailability
) -> None:
    result = normalize_google_sheet_row(valid_row(Status=source))
    assert result.normalized is not None
    assert result.normalized.availability is expected


def test_unknown_status_fails_closed() -> None:
    result = normalize_google_sheet_row(valid_row(Status="Probably available"))
    assert result.state is RowValidationState.INVALID_SOURCE_ROW
    assert result.normalized is None
    assert "approved property status" in result.errors[0]


@pytest.mark.parametrize("missing", ["Property Address", "City", "State", "ZIP"])
def test_missing_required_address_information_is_clear(missing: str) -> None:
    result = normalize_google_sheet_row(valid_row(**{missing: ""}))
    assert result.state is RowValidationState.MISSING_REQUIRED_INFORMATION
    assert result.normalized is None
    assert any("required" in error.lower() for error in result.errors)


@pytest.mark.parametrize("source_id", ["", "42", "row 42", "sheet-row-9"])
def test_rejects_missing_or_unstable_source_identity(source_id: str) -> None:
    result = normalize_google_sheet_row(valid_row(**{"Inventory ID": source_id}))
    assert result.normalized is None
    assert any("row number" in error.lower() for error in result.errors)


def test_rejects_malformed_numeric_and_source_timestamp() -> None:
    result = normalize_google_sheet_row(
        valid_row(Price="call for price", **{"Updated At": "yesterday"})
    )
    assert result.state is RowValidationState.INVALID_SOURCE_ROW
    assert result.normalized is None
    assert any("number" in error for error in result.errors)
    assert any("ISO-8601" in error for error in result.errors)


def test_hash_is_deterministic_across_column_order() -> None:
    source = valid_row()
    reordered = dict(reversed(tuple(source.items())))
    assert normalize_google_sheet_row(source).source_row_hash == normalize_google_sheet_row(
        reordered
    ).source_row_hash


def test_does_not_invent_optional_values() -> None:
    source = valid_row()
    source.pop("Price")
    source.pop("Down")
    result = normalize_google_sheet_row(source)
    assert result.normalized is not None
    assert result.normalized.total_price is None
    assert result.normalized.down_payment is None


def test_invalid_state_and_zip_fail_closed() -> None:
    result = normalize_google_sheet_row(valid_row(State="Georgia", ZIP="3030"))
    assert result.state is RowValidationState.INVALID_SOURCE_ROW
    assert len(result.errors) == 2


def test_source_metadata_is_preserved_without_row_contents() -> None:
    result = normalize_google_sheet_row(valid_row(), source_label="Mock seller sheet")
    assert result.source_label == "Mock seller sheet"
    assert result.source_record_id == "CFH-ATL-1001"
    assert result.source_updated_at == "2026-09-04T12:00:00Z"
    assert "101 Main St" not in result.source_row_hash


def test_preserves_optional_inventory_routing_fields_through_safe_aliases() -> None:
    result = normalize_google_sheet_row(
        valid_row(
            **{
                "Home Type": "Single Family",
                "Finance Type": "Owner Financing",
                "Assigned Team": "Atlanta acquisitions",
                "Market Name": "Atlanta",
                "Campaign Name": "Fall inventory",
            }
        )
    )
    assert result.normalized is not None
    assert result.normalized.property_type == "Single Family"
    assert result.normalized.financing_type == "Owner Financing"
    assert result.normalized.assigned_worker_or_team == "Atlanta acquisitions"
    assert result.normalized.market == "Atlanta"
    assert result.normalized.campaign == "Fall inventory"


def test_does_not_invent_optional_inventory_routing_fields() -> None:
    result = normalize_google_sheet_row(valid_row())
    assert result.normalized is not None
    assert result.normalized.property_type is None
    assert result.normalized.financing_type is None
    assert result.normalized.assigned_worker_or_team is None
    assert result.normalized.market is None
    assert result.normalized.campaign is None


def test_v14_contract_fields_are_preserved_as_internal_inventory_facts() -> None:
    result = normalize_google_sheet_row(
        valid_row(
            sheet_row=12,
            lockbox_code="TEST",
            monthly_principal_interest="900",
            monthly_insurance="100",
            monthly_taxes="150",
            legal_description="Fictional legal description",
            parcel_number="TEST-PARCEL",
        )
    )
    assert result.normalized is not None
    assert result.normalized.source_row_number == 12
    assert result.normalized.lockbox_code == "TEST"
    assert str(result.normalized.monthly_principal_interest) == "900"
    assert result.normalized.legal_description == "Fictional legal description"
