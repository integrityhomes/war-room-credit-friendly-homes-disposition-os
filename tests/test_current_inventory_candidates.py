import copy
from dataclasses import replace

from test_property_import_reconciliation import rows

from cfh_disposition.property_import_reconciliation import build_current_inventory_candidates


def test_detail_errors_do_not_block_identity_safe_current_inventory():
    row = rows()[0]
    warning = {"column": 3, "field": "beds", "header": "Beds", "raw": "1/1", "normalized": None, "review": "Ambiguous count"}
    yellow = replace(row, issues=("Bedrooms must be a number.",), source_fields=(warning,))
    white = replace(yellow, row=8, marketing_status="white", fields={**row.fields, "address": "202 Fiction Lane"})
    history = replace(row, row=99, tab="SOLD", fields={**row.fields, "address": "303 Old Lane"})
    source = [yellow, white, history]
    before = copy.deepcopy(source)
    result = build_current_inventory_candidates(source, [])
    assert result["total_candidates"] == result["total_ready"] == 2
    assert result["summary"]["Yellow"]["previously_blocked_detail_only"] == 1
    assert result["summary"]["White"]["previously_blocked_detail_only"] == 1
    assert result["field_warning_count"] == 2
    assert result["historical_only_included"] == result["records_written"] == result["checkpoints_written"] == 0
    assert source == before and not result["checkpoint_proposals"]


def test_duplicate_current_rows_and_source_id_conflict_still_block():
    row = rows()[0]
    result = build_current_inventory_candidates([row, replace(row, row=10)], [])
    assert result["total_ready"] == 0 and result["summary"]["Yellow"]["blocked"] == 1
    prop = {**row.fields, "id": "canonical", "external_id": "same-source", "address": "404 Another Lane"}
    result = build_current_inventory_candidates([replace(row, external_id="same-source")], [prop])
    assert result["total_ready"] == 0


def test_history_is_retained_and_clocks_are_proposals_only():
    row = rows()[0]
    history = replace(row, tab="SOLD", row=99)
    result = build_current_inventory_candidates([history, row], [])
    assert result["total_ready"] == 1
    assert result["properties"][0]["historical_occurrences"][0]["closing_verified"] is False
    prop = {**row.fields, "id": "canonical"}
    result = build_current_inventory_candidates([row], [prop])
    assert result["total_ready"] == 0 and len(result["checkpoint_proposals"]) == 1
    assert result["checkpoint_proposals"][0]["proposed_checkpoint_patch"]["marketing_observed_since"] == result["observed_at"]
    assert result["checkpoints_written"] == 0
