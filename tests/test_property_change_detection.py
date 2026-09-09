from dataclasses import replace

import pytest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.property_change_detection import (
    RETURNED,
    SOLD_CHANGE,
    DetectionState,
    detect_property_changes,
)
from cfh_disposition.property_sync_preview import MISSING, NEW, OTHER, PRICE, STATUS, TERMS


def detect(rows, properties=None, previous=None):
    return detect_property_changes(rows, [property_record()] if properties is None else properties,
                                   source_reference="fictional", previous=previous)


@pytest.mark.parametrize(("field", "value", "kind"), [
    ("asking_or_sale_price", "110000", PRICE), ("monthly_payment", "950", TERMS),
    ("availability", "Pending", STATUS), ("availability", "Sold / Unavailable", SOLD_CHANGE),
    ("notes", "Verified fictional repair note", OTHER),
])
def test_every_semantic_change_is_detected_without_mutations(field, value, kind):
    row = source_row(**{field: value})
    result = detect([row])
    assert result.counts[kind] == 1 and len(result.new_events) == 1
    assert result.records_written == result.external_actions_started == 0


def test_new_and_unchanged():
    assert detect([source_row()], []).counts[NEW] == 1
    result = detect([source_row()])
    assert not result.changes and result.unchanged == 1


def test_sold_returns_to_active_and_does_not_create_closing_facts():
    result = detect([source_row()], [property_record(availability="Sold / Unavailable")])
    assert result.counts[RETURNED] == result.counts[STATUS] == 1
    assert result.counts[SOLD_CHANGE] == 0


def test_disappearance_is_review_only_even_with_invalid_source_rows():
    for rows in ([], [replace(source_row(address="999 Fiction Lane"), issues=("Bad source",))]):
        result = detect(rows, [property_record(source="cfh-google-sheet", sync_metadata={"source_reference_hash": "fictional"})])
        assert result.counts[MISSING] == 1 and result.counts[SOLD_CHANGE] == 0
        assert result.changes[0].categories == (MISSING,)


def test_unrelated_canonical_property_is_not_missing_from_this_source():
    assert not detect([]).changes


def test_duplicate_and_invalid_rows_never_become_change_events():
    result = detect([source_row(), source_row()], [])
    assert result.review_rows == 2 and not result.changes
    result = detect([replace(source_row(), issues=("Bad amount",))])
    assert result.review_rows == 1 and not result.changes


def test_repeat_and_restored_checkpoint_do_not_duplicate_events():
    rows = [source_row(asking_or_sale_price="110000")]
    first = detect(rows)
    restored = DetectionState.from_checkpoint(first.state.checkpoint())
    second = detect(rows, previous=restored)
    assert len(first.new_events) == 1 and second.new_events == ()
    assert first.changes == second.changes and first.state == second.state
    third = detect([source_row(asking_or_sale_price="120000")], previous=second.state)
    assert len(third.new_events) == 1


def test_formatting_and_reordering_do_not_change_fingerprint_or_alerts():
    row = source_row(asking_or_sale_price="110000")
    first = detect([row])
    second = detect([replace(row, row=900, tab="Moved", fields={**row.fields, "asking_or_sale_price": "$110,000.00"})], previous=first.state)
    assert second.state == first.state and not second.new_events


@pytest.mark.parametrize(("query", "rows", "properties", "label"), [
    ("What properties changed?", [source_row(monthly_payment="950")], [property_record()], TERMS),
    ("What new properties were added?", [source_row()], [], NEW),
    ("Which prices changed?", [source_row(asking_or_sale_price="110000")], [property_record()], PRICE),
    ("What became sold or unavailable?", [source_row(availability="Sold / Unavailable")], [property_record()], SOLD_CHANGE),
])
def test_corepilot_property_change_answers(query, rows, properties, label):
    result = run_corepilot(query, {}, property_changes=detect(rows, properties))
    assert result.status == "complete" and label in result.what_i_found[0]
    assert result.records_written == 0


def test_attention_uses_read_only_next_action_and_missing_check_does_not_claim_unchanged():
    result = run_corepilot("What needs my attention?", {}, property_changes=detect([source_row(asking_or_sale_price="110000")]))
    assert "property change" in result.what_i_found[0]
    assert "Property Changes" in result.recommended_next_step
    assert run_corepilot("Which prices changed?", {}).status == "needs_context"
