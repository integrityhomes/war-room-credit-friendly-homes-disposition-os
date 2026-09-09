from dataclasses import replace

import pytest
from test_property_baseline import source_rows
from test_property_sync_preview import property_record, source_row

from cfh_disposition.property_change_detection import detect_property_changes
from cfh_disposition.property_change_review import apply_property_update, prepare_from_snapshot, prepare_patch
from cfh_disposition.property_sync_preview import MISSING, REVIEW, FieldChange


def detection(rows, properties):
    return detect_property_changes(rows, properties, source_reference="fictional")


@pytest.mark.parametrize(("field", "old", "new"), [
    ("asking_or_sale_price", "89000", "84900"), ("monthly_payment", "925", "895"),
    ("availability", "Available", "Sold / Unavailable"), ("availability", "Sold / Unavailable", "Available"),
    ("down_payment", "1000", "2000"), ("interest_rate", "10", "9"),
    ("monthly_insurance", "40", "50"), ("monthly_taxes", "100", "105"),
    ("bedrooms", 2, 3), ("bathrooms", "1", "1.5"), ("square_feet", 1000, 1100),
])
def test_exact_patch_and_simulated_apply_resolves_pending(field, old, new):
    record = property_record(**{field: old})
    rows = [source_row(**{field: new})]
    before = dict(record)
    first = detection(rows, [record])
    proposal = prepare_from_snapshot(first.changes[0].event_id, rows, [record], "fictional")
    assert proposal.patch == {field: new} and proposal.expected_values == {field: old}
    assert not proposal.errors and not proposal.apply_enabled and record == before
    simulated = {**record, **proposal.patch}
    assert not detection(rows, [simulated]).changes
    assert not detect_property_changes(rows, [record], source_reference="fictional", previous=first.state).new_events
    assert "closed_at" not in simulated and "closing_date" not in simulated and "stage" not in simulated


@pytest.mark.parametrize("value", ["", "N/A", "not applicable", "unclear", "925 plus insurance", "NaN", "-10"])
def test_blank_or_invalid_evidence_cannot_prepare_any_patch(value):
    record = property_record()
    change = detection([source_row(monthly_payment="895")], [record]).changes[0]
    change = replace(change, evidence=replace(change.evidence, changes=(FieldChange("monthly_payment", "900", value),)))
    proposal = prepare_patch(change, record)
    assert proposal.errors and not proposal.patch


def test_invalid_source_remains_excluded_and_missing_never_changes_status():
    record = property_record(source="cfh-google-sheet", sync_metadata={"source_reference_hash": "fictional"})
    invalid = replace(source_row(), issues=("Ambiguous insurance",))
    result = detection([invalid], [record])
    assert result.review_rows == 1 and not result.changes
    missing = detection([], [record]).changes[0]
    assert missing.categories == (MISSING,)
    assert not prepare_patch(missing, record).patch


def test_stale_source_and_canonical_changes_block_review():
    record = property_record()
    rows = [source_row(monthly_payment="895")]
    event = detection(rows, [record]).changes[0]
    assert prepare_patch(event, {**record, "monthly_payment": "850"}).errors
    assert prepare_from_snapshot(event.event_id, [source_row(monthly_payment="800")], [record], "fictional").errors


def test_price_alias_updates_existing_field_without_creating_shadow_value():
    record = property_record()
    record["asking_price"] = record.pop("asking_or_sale_price")
    event = detection([source_row(asking_or_sale_price="90000")], [record]).changes[0]
    assert prepare_patch(event, record).patch == {"asking_price": "90000"}


def test_new_property_uses_baseline_validation_and_duplicates_fail_closed():
    rows = source_rows()
    event = detection(rows, []).changes[0]
    proposal = prepare_from_snapshot(event.event_id, rows, [], "fictional")
    assert proposal.new_property and not proposal.patch and not proposal.apply_enabled
    assert proposal.new_property["sync_metadata"]["closing_verified"] is False
    assert prepare_from_snapshot(event.event_id, [*rows, rows[0]], [], "fictional").errors


def test_review_category_and_live_apply_gate_cannot_be_bypassed():
    record = property_record()
    event = detection([source_row(monthly_payment="895")], [record]).changes[0]
    assert not prepare_patch(replace(event, categories=(REVIEW,)), record).patch
    with pytest.raises(PermissionError, match="disabled"):
        apply_property_update(approved=True, force=True)


@pytest.mark.parametrize("query", ["Show me price changes.", "What needs property review?", "Which properties became unavailable?", "Which properties came back active?"])
def test_corepilot_review_questions(query):
    from cfh_disposition.corepilot_orchestrator import run_corepilot
    result = run_corepilot(query, {}, property_changes=detection([source_row(asking_or_sale_price="90000")], [property_record()]))
    assert result.status == "complete" and result.records_written == 0


def test_corepilot_specific_property_requires_context_and_filters_results():
    from cfh_disposition.corepilot_orchestrator import run_corepilot
    record = property_record()
    changes = detection([source_row(monthly_payment="895")], [record])
    assert run_corepilot("What changed on this property?", {}, property_changes=changes).status == "needs_context"
    result = run_corepilot("What changed on 101 Example Lane?", {"properties": [record]}, property_changes=changes)
    assert result.status == "complete" and "PAYMENT/TERMS" in result.what_i_found[0]
