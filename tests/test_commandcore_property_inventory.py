from datetime import UTC, datetime, timedelta

from cfh_disposition.commandcore_property_inventory import (
    CanonicalPropertyRecord,
    FieldProvenance,
    InventoryValidationState,
    SyncResultState,
    address_fingerprint,
    deterministic_property_id,
    marketing_inventory_result,
    plan_inventory_sync,
    plan_property_sync,
    secretary_inventory_result,
)
from cfh_disposition.google_sheet_property_rows import CanonicalAvailability, normalize_google_sheet_row

NOW = datetime(2026, 9, 4, 12, tzinfo=UTC)


def normalized(**updates: object):
    row: dict[str, object] = {
        "source_record_id": "PROPERTY-A1",
        "source_updated_at": "2026-09-04T11:00:00Z",
        "address": "123 Main Street",
        "city": "Springfield",
        "state": "MO",
        "zip": "65801",
        "status": "Marketing Live",
        "property_type": "Single Family",
        "bedrooms": "3",
        "bathrooms": "2",
        "price": "$150,000",
        "down_payment": "$10,000",
        "monthly_payment": "$1,250",
        "financing_type": "Owner financing",
        "assigned_worker": "Existing Team Assignment",
        "market": "Springfield",
        "campaign": "Fall inventory",
    }
    row.update(updates)
    return normalize_google_sheet_row(row, source_label="Daily Property Sheet")


def existing_record(**updates: object) -> CanonicalPropertyRecord:
    source = normalized().normalized
    assert source is not None
    property_id = deterministic_property_id(source.source_label, source.source_record_id)
    values: dict[str, object] = {
        "commandcore_property_id": property_id,
        "source_label": source.source_label,
        "source_record_id": source.source_record_id,
        "source_row_hash": source.source_row_hash,
        "source_updated_at": source.source_updated_at,
        "address": source.address,
        "city": source.city,
        "state": source.state,
        "zip_code": source.zip_code,
        "county": source.county or "",
        "availability": source.availability,
        "detailed_internal_status": "Ready to Launch",
        "property_type": source.property_type or "",
        "bedrooms": source.bedrooms,
        "bathrooms": source.bathrooms,
        "square_feet": source.square_feet,
        "asking_or_sale_price": source.total_price,
        "down_payment": source.down_payment,
        "monthly_payment": source.monthly_payment,
        "interest_rate": source.interest_rate,
        "term_months": source.term_months,
        "financing_type": source.financing_type or "",
        "condition_or_repair_notes": source.condition_summary or "",
        "assigned_worker_or_team": source.assigned_worker_or_team or "",
        "market": source.market or "",
        "campaign": source.campaign or "",
        "public_marketing_eligible": True,
        "last_commandcore_sync": NOW,
        "validation_state": InventoryValidationState.VERIFIED,
        "source_of_truth": True,
        "provenance": (
            FieldProvenance(
                field_name="address",
                source_label=source.source_label,
                source_record_id=source.source_record_id,
                source_row_hash=source.source_row_hash,
                source_updated_at=source.source_updated_at,
                commandcore_synced_at=NOW,
            ),
        ),
    }
    values.update(updates)
    return CanonicalPropertyRecord(**values)


def test_deterministic_identity_and_normalized_address_are_stable() -> None:
    first = deterministic_property_id("Daily Property Sheet", "PROPERTY-A1")
    second = deterministic_property_id(" daily property sheet ", "property-a1")
    assert first == second
    row = normalized(address="123 MAIN ST.").normalized
    assert row is not None
    assert address_fingerprint(row) == "123mainst:springfield:mo:65801"


def test_new_property_uses_deterministic_id_and_no_external_write() -> None:
    result = plan_property_sync(normalized(), [], synced_at=NOW)
    assert result.state is SyncResultState.NEW_PROPERTY
    assert result.commandcore_property_id == deterministic_property_id("Daily Property Sheet", "PROPERTY-A1")
    assert result.records_written == 0
    assert result.external_action_started is False
    assert result.record and result.record.source_of_truth


def test_known_property_update_reuses_same_property_id_and_assignment() -> None:
    existing = existing_record()
    result = plan_property_sync(normalized(price="$155,000"), [existing], synced_at=NOW + timedelta(hours=1))
    assert result.state is SyncResultState.UPDATED
    assert result.commandcore_property_id == existing.commandcore_property_id
    assert result.record and str(result.record.asking_or_sale_price) == "155000"
    assert result.record.assigned_worker_or_team == "Existing Team Assignment"


def test_partial_update_preserves_assignment_internal_status_and_provenance() -> None:
    existing = existing_record(detailed_internal_status="Available - owner verified")
    update = normalized(price="$155,000", assigned_worker=None)
    result = plan_property_sync(update, [existing], synced_at=NOW + timedelta(hours=1))
    assert result.record is not None
    assert result.record.assigned_worker_or_team == "Existing Team Assignment"
    assert result.record.detailed_internal_status == "Available - owner verified"
    assert {item.field_name for item in result.record.provenance} >= {
        "address",
        "total_price",
    }


def test_same_row_returns_no_change() -> None:
    existing = existing_record(detailed_internal_status="Ready to Launch")
    result = plan_property_sync(normalized(), [existing], synced_at=NOW + timedelta(hours=1))
    assert result.state is SyncResultState.NO_CHANGE


def test_ambiguous_address_fails_closed() -> None:
    one = existing_record(commandcore_property_id="property-1")
    two = existing_record(commandcore_property_id="property-2", source_record_id="PROPERTY-B2")
    result = plan_property_sync(normalized(source_record_id="PROPERTY-C3"), [one, two], synced_at=NOW)
    assert result.state is SyncResultState.NEEDS_REVIEW
    assert result.record is None


def test_commandcore_id_cannot_silently_move_to_another_address() -> None:
    existing = existing_record()
    result = plan_property_sync(
        normalized(commandcore_property_id=existing.commandcore_property_id, address="999 Different Street"),
        [existing],
        synced_at=NOW,
    )
    assert result.state is SyncResultState.NEEDS_REVIEW
    assert result.conflicts[0].field_name == "property_identity"


def test_different_source_conflict_reports_values_and_provenance() -> None:
    existing = existing_record(source_label="Verified CommandCore Review", source_record_id="REVIEWED-1")
    result = plan_property_sync(normalized(price="$175,000"), [existing], synced_at=NOW)
    assert result.state is SyncResultState.NEEDS_REVIEW
    price = next(item for item in result.conflicts if item.field_name == "total_price")
    assert price.existing_value == "150000"
    assert price.proposed_value == "175000"
    assert "Verified CommandCore Review" in price.existing_source


def test_stale_source_update_needs_review() -> None:
    result = plan_property_sync(
        normalized(source_updated_at="2026-09-01T10:00:00Z"),
        [existing_record(source_updated_at="2026-09-03T10:00:00Z")],
        synced_at=NOW,
    )
    assert result.state is SyncResultState.NEEDS_REVIEW
    assert "older" in result.reasons[0]


def test_batch_duplicate_source_or_address_is_not_planned_twice() -> None:
    results = plan_inventory_sync([normalized(), normalized()], [], synced_at=NOW)
    assert [item.state for item in results] == [SyncResultState.DUPLICATE, SyncResultState.DUPLICATE]
    address_duplicate = plan_inventory_sync([normalized(), normalized(source_record_id="PROPERTY-B2")], [], synced_at=NOW)
    assert all(item.state is SyncResultState.DUPLICATE for item in address_duplicate)


def test_invalid_and_missing_rows_keep_explicit_results() -> None:
    missing = normalize_google_sheet_row({"source_record_id": "PROPERTY-X"}, source_label="Daily Property Sheet")
    invalid = normalized(state="Missouri")
    assert plan_property_sync(missing, []).state is SyncResultState.MISSING_REQUIRED_INFORMATION
    assert plan_property_sync(invalid, []).state is SyncResultState.INVALID_SOURCE_ROW


def test_statuses_are_safe_for_secretary_and_marketing() -> None:
    for status in ("Pending", "Sold", "Paused"):
        planned = plan_property_sync(normalized(status=status), [], synced_at=NOW)
        assert planned.record is not None
        marketing = marketing_inventory_result(planned.record)
        assert marketing.eligible_for_new_marketing is False
        assert marketing.shutdown_recommended is True
        assert marketing.campaign_action_started is False
        secretary = secretary_inventory_result(planned.record, now=NOW)
        assert secretary.facts is not None
        assert secretary.facts.availability.value in {"Pending", "Sold / Unavailable", "Paused"}
        assert secretary.source_is_ai_memory is False


def test_coming_soon_exists_but_is_not_publicly_available() -> None:
    planned = plan_property_sync(normalized(status="Coming Soon"), [], synced_at=NOW)
    assert planned.record and planned.record.availability is CanonicalAvailability.COMING_SOON
    assert planned.record.public_marketing_eligible is False
    assert marketing_inventory_result(planned.record).eligible_for_new_marketing is False


def test_secretary_refuses_missing_stale_or_conflicting_inventory() -> None:
    assert secretary_inventory_result(None, now=NOW).needs_confirmation
    stale = existing_record(last_commandcore_sync=NOW - timedelta(days=2))
    assert secretary_inventory_result(stale, now=NOW).needs_confirmation
    conflicting = existing_record(validation_state=InventoryValidationState.NEEDS_REVIEW, source_of_truth=False)
    assert secretary_inventory_result(conflicting, now=NOW).needs_confirmation
    fresh = existing_record()
    result = secretary_inventory_result(fresh, now=NOW)
    assert result.needs_confirmation is False
    assert result.facts and result.facts.price == "150000"


def test_planner_never_writes_or_starts_campaign_actions() -> None:
    result = plan_property_sync(normalized(status="Sold"), [], synced_at=NOW)
    assert result.records_written == 0
    assert result.external_action_started is False
    assert result.campaign_shutdown_started is False
    assert result.marketing_review_required is True
