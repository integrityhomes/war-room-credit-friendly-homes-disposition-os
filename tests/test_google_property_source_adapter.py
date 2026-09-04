from datetime import UTC, datetime, timedelta

from cfh_disposition.commandcore_property_inventory import (
    SyncResultState,
    marketing_inventory_result,
    plan_inventory_sync,
    plan_property_sync,
    secretary_inventory_result,
)
from cfh_disposition.google_property_source_adapter import (
    V14PropertySourceContext,
    V14PropertySourceType,
    adapt_v14_property_row,
)
from cfh_disposition.google_sheet_property_rows import CanonicalAvailability, RowValidationState

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def context(source_type: V14PropertySourceType = V14PropertySourceType.DIRECT_GOOGLE_SHEET):
    return V14PropertySourceContext(
        source_type=source_type,
        source_reference="fictional-source-reference",
        tab_name="Properties",
    )


def v14_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sheet_row": 9,
        "property_address": "123 Example Avenue, Springfield, MO 65801",
        "lockbox_code": "TEST-ONLY",
        "beds": 3,
        "baths": 2,
        "square_feet": 1400,
        "down_payment": 10000,
        "total_monthly_payment": 1250,
        "sales_price": 150000,
        "interest_rate": 8.5,
        "monthly_principal_interest": 1000,
        "monthly_insurance": 100,
        "monthly_taxes": 150,
        "insurance_included": "Yes",
        "photo_link": "https://example.invalid/property-photo",
        "legal_description": "Fictional legal description",
        "parcel_number": "TEST-PARCEL-001",
        "last_tax_bill": 1800,
        "fair_cash_value": 145000,
        "assessed_value": 48000,
        "lender": "Example lender",
        "payment_system": "Example servicing",
        "seller_entity": "Example Homes LLC",
        "seller_address": "456 Example Road",
        "seller_state": "MO",
        "seller_email": "seller@example.invalid",
        "notes": "Fictional test row",
        "date_added": "2026-08-01",
        "last_update": "2026-09-04T11:00:00Z",
    }
    row.update(updates)
    return row


def test_v14_mapping_preserves_confirmed_fields_without_google_access() -> None:
    result = adapt_v14_property_row(v14_row(), context=context())
    assert result.state is RowValidationState.VALID
    row = result.normalized
    assert row is not None
    assert row.address == "123 Example Avenue"
    assert row.source_type == "Direct Google Sheet"
    assert row.source_tab == "Properties"
    assert row.source_reference_hash and "fictional-source-reference" not in row.source_reference_hash
    assert row.lockbox_code == "TEST-ONLY"
    assert str(row.total_price) == "150000"
    assert str(row.monthly_principal_interest) == "1000"
    assert row.legal_description == "Fictional legal description"
    assert row.parcel_number == "TEST-PARCEL-001"
    assert row.availability is CanonicalAvailability.COMING_SOON


def test_sheet_and_xlsx_shapes_share_deterministic_identity() -> None:
    direct = adapt_v14_property_row(v14_row(sheet_row=9), context=context())
    xlsx = adapt_v14_property_row(
        v14_row(sheet_row=41),
        context=context(V14PropertySourceType.DRIVE_XLSX),
    )
    direct_plan = plan_property_sync(direct, [], synced_at=NOW)
    xlsx_plan = plan_property_sync(xlsx, [], synced_at=NOW)
    assert direct_plan.commandcore_property_id == xlsx_plan.commandcore_property_id
    batch = plan_inventory_sync([direct, xlsx], [], synced_at=NOW)
    assert all(item.state is SyncResultState.DUPLICATE for item in batch)


def test_partial_update_preserves_verified_values_and_assignment() -> None:
    initial = plan_property_sync(adapt_v14_property_row(v14_row(), context=context()), [], synced_at=NOW)
    assert initial.record is not None
    existing = initial.record.model_copy(
        update={"assigned_worker_or_team": "Existing Worker", "lockbox_code": "VERIFIED-LOCKBOX"}
    )
    partial = adapt_v14_property_row(
        v14_row(lockbox_code="", sales_price=155000, sheet_row=55),
        context=context(),
    )
    updated = plan_property_sync(partial, [existing], synced_at=NOW + timedelta(hours=1))
    assert updated.record is not None
    assert updated.record.commandcore_property_id == existing.commandcore_property_id
    assert updated.record.assigned_worker_or_team == "Existing Worker"
    assert updated.record.lockbox_code == "VERIFIED-LOCKBOX"
    assert str(updated.record.asking_or_sale_price) == "155000"


def test_incomplete_address_fails_closed() -> None:
    result = adapt_v14_property_row(v14_row(property_address="123 Example Avenue"), context=context())
    assert result.state is RowValidationState.MISSING_REQUIRED_INFORMATION
    assert result.normalized is None


def test_source_row_never_makes_property_publicly_available() -> None:
    planned = plan_property_sync(adapt_v14_property_row(v14_row(), context=context()), [], synced_at=NOW)
    assert planned.record is not None
    assert marketing_inventory_result(planned.record).eligible_for_new_marketing is False
    secretary = secretary_inventory_result(planned.record, now=NOW)
    assert secretary.facts is not None
    assert secretary.facts.availability.value == "Coming Soon"
    assert secretary.source_is_ai_memory is False
