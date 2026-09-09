import copy
from dataclasses import replace

import pytest

from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues
from cfh_disposition.property_baseline import BaselineExpectation, build_baseline_plan, import_baseline
from cfh_disposition.property_sync_preview import INVENTORY_TABS, SheetProperty, regional_sheet_properties


def source_rows(active=1, sold=0, review=0):
    header = ["Property", "Lock box code", "Beds", "Baths", "Sq Ft", "Down Payment", "Monthly", "Sales Price"]
    def row(number):
        return [f"{1000 + number} Example Lane, Example City, IL 60000", "", "3", "2", "1200", "5000", "900", "100000"]
    sheets = []
    for tab in INVENTORY_TABS:
        values = [header]
        if tab == INVENTORY_TABS[0]:
            values.extend(row(i) for i in range(active))
            values.extend([f"Unrecognized source item {i}"] for i in range(review))
        if tab == "SOLD":
            values.extend(row(i + active) for i in range(sold))
        sheets.append(ReadOnlyWorksheetValues(tab, values))
    return regional_sheet_properties(sheets, "fictional-sheet")


def plan_for(rows, existing=(), active=1, sold=0, review=0, **kwargs):
    return build_baseline_plan(rows, existing, source_reference_hash="fictional-source-fingerprint",
                               expectation=BaselineExpectation(active + sold, active, sold, review), **kwargs)


def test_validated_scope_excludes_all_review_rows_and_creates_only_proposals():
    rows = source_rows(29, 126, 300)
    before = copy.deepcopy(rows)
    plan = build_baseline_plan(rows, [], source_reference_hash="fictional-source-fingerprint")
    assert len(plan.properties) == 155
    assert (plan.active_count, plan.sold_count, plan.skipped_review) == (29, 126, 300)
    assert not plan.errors and not plan.import_enabled
    assert plan.deletions == plan.updates == plan.deals_created == plan.records_written == 0
    assert rows == before
    assert len({item.record["id"] for item in plan.properties}) == 155
    for item in plan.properties:
        record = item.record
        assert record["entity_type"] == "properties"
        assert record["links"] == {}
        assert "stage" not in record and "closed_at" not in record
        assert record["sync_metadata"]["closing_verified"] is False
        assert record["parcel_number"] is None


def test_source_metadata_and_semantic_facts_are_preserved():
    row = replace(source_rows()[0], external_id="external-fictional")
    plan = plan_for([row])
    record = plan.properties[0].record
    assert record["external_id"] == "external-fictional"
    assert record["source_record_id"] == row.fields["source_record_id"]
    assert record["zip"] == "60000"
    assert record["asking_or_sale_price"] == "100000"
    assert record["monthly_payment"] == "900"
    metadata = record["sync_metadata"]
    assert metadata["identity_method"] == "External source ID"
    assert metadata["source_tab"] == row.tab
    assert metadata["source_row_hash"] == row.fields["source_row_hash"]
    assert metadata["normalized_facts_hash"] and metadata["source_reference_hash"]


def test_baseline_uses_same_canonical_id_on_repeat_and_does_not_duplicate_existing():
    rows = source_rows()
    first = plan_for(rows)
    second = plan_for(rows)
    assert first.properties[0].record["id"] == second.properties[0].record["id"]
    existing = [first.properties[0].record]
    before = copy.deepcopy(existing)
    repeated = plan_for(rows, existing)
    assert not repeated.properties and repeated.duplicates_prevented == 1
    assert repeated.errors and repeated.updates == 0
    assert existing == before


def test_duplicate_input_is_excluded_instead_of_silently_imported():
    row = source_rows()[0]
    plan = plan_for([row, replace(row, row=99)], active=0, review=2)
    assert not plan.properties
    assert plan.skipped_review == plan.duplicates_prevented == 2


def test_external_id_conflict_cannot_create_another_property():
    row = replace(source_rows()[0], external_id="external-fictional")
    existing = {**row.fields, "id": "existing", "address": "999 Other Lane", "external_id": "external-fictional"}
    plan = plan_for([row], [existing])
    assert not plan.properties and plan.skipped_review == 1


def test_new_external_id_does_not_duplicate_existing_address_identity():
    row = source_rows()[0]
    existing = plan_for([row]).properties[0].record
    plan = plan_for([replace(row, external_id="newly-available-external")], [existing])
    assert not plan.properties and plan.duplicates_prevented == 1


def test_classification_mismatch_and_unvalidated_facts_block_candidates():
    row = source_rows()[0]
    mismatch = replace(row, fields={**row.fields, "availability": "Sold / Unavailable"})
    assert not plan_for([mismatch]).properties
    invalid = replace(row, fields={**row.fields, "asking_or_sale_price": "unconfirmed"})
    plan = plan_for([invalid])
    assert not plan.properties and plan.errors


def test_counts_drifting_from_validated_scope_are_reported_as_errors():
    plan = build_baseline_plan(source_rows(), [], source_reference_hash="fictional-source")
    assert any("Baseline scope changed" in error for error in plan.errors)
    assert not plan.import_enabled


def test_content_fingerprint_is_order_independent_but_tracks_fact_changes():
    rows = source_rows(2)
    first = plan_for(rows, active=2, observed_at="2026-09-09T00:00:00Z")
    reordered = [replace(row, row=row.row + 10) for row in reversed(rows)]
    second = plan_for(reordered, active=2, observed_at="2026-09-10T00:00:00Z")
    assert first.snapshot_hash == second.snapshot_hash
    changed = [replace(rows[0], fields={**rows[0].fields, "asking_or_sale_price": "110000"}), rows[1]]
    assert plan_for(changed, active=2).snapshot_hash != first.snapshot_hash


def test_returned_records_cannot_mutate_the_reviewed_snapshot():
    plan = plan_for(source_rows())
    record = plan.properties[0].record
    record["asking_or_sale_price"] = "1"
    assert plan.properties[0].record["asking_or_sale_price"] == "100000"


def test_import_gate_cannot_be_bypassed_with_approval_arguments():
    with pytest.raises(PermissionError, match="import is disabled"):
        import_baseline(plan_for(source_rows()), approved=True, apply=True, allow_import=True)


def test_missing_source_reference_is_an_error():
    plan = build_baseline_plan(source_rows(), [], source_reference_hash="", expectation=BaselineExpectation(1, 1, 0, 0))
    assert "Source reference fingerprint is missing." in plan.errors


def test_manual_review_row_never_enters_payload_even_with_valid_looking_facts():
    row = source_rows()[0]
    review = SheetProperty(row.tab, row.row, row.fields, issues=("Human review required.",))
    plan = plan_for([review], active=0, review=1)
    assert plan.properties == () and plan.skipped_review == 1
