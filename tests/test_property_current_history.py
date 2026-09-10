import copy
import json
from dataclasses import replace
from datetime import date

import pytest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.corepilot_inventory import inventory_items, observe_inventory, stale_checkpoint
from cfh_disposition.property_change_cache import decode_result, encode_result
from cfh_disposition.property_change_detection import RETURNED, SOLD_CHANGE, detect_property_changes
from cfh_disposition.property_sync_preview import HISTORY, MISSING, NEW, REVIEW, compare_properties


def pair():
    return [replace(source_row(), marketing_status="yellow", row=8),
            replace(source_row(availability="Sold / Unavailable", lockbox_code="fictional-protected"), tab="SOLD", row=20)]


@pytest.mark.parametrize("reverse", [False, True])
def test_history_is_retained_but_only_current_can_propose_a_property(reverse):
    rows = pair()[::-1] if reverse else pair()
    snapshot = copy.deepcopy(rows)
    result = compare_properties(rows, [])
    assert result.counts[NEW] == 1 and result.counts[REVIEW] == 0
    current = next(item for item in result.items if NEW in item.categories)
    assert current.historical_occurrences == (("SOLD", 20),)
    assert sum(HISTORY in item.categories for item in result.items) == 1
    assert rows == snapshot


def test_invalid_current_and_competing_current_rows_do_not_fall_back_to_sold():
    current, historical = pair()
    bad = replace(current, issues=("Ambiguous payment",))
    result = compare_properties([bad, historical], [])
    assert result.items[0].categories == (REVIEW,)
    assert result.items[1].categories == (HISTORY,)
    result = compare_properties([current, replace(current, row=10), historical], [])
    assert result.counts[NEW] == 0 and result.counts[REVIEW] == 2


def test_conflicting_external_identity_remains_blocked():
    current, history = pair()
    result = compare_properties([replace(current, external_id="source-a"), replace(history, external_id="source-b")], [])
    assert result.counts[NEW] == 0
    assert "Source IDs disagree" in result.items[0].reason
    prop = property_record(external_id="canonical-source")
    result = compare_properties([current, replace(history, external_id="different-source")], [prop])
    assert not result.items[1].property_id


@pytest.mark.parametrize("reverse", [False, True])
def test_return_uses_existing_record_and_retains_private_idempotent_history(reverse):
    rows = pair()[::-1] if reverse else pair()
    prop = property_record(availability="Sold / Unavailable")
    before = copy.deepcopy(prop)
    result = detect_property_changes(rows, [prop], source_reference="fictional")
    assert result.counts[RETURNED] == 1 and result.counts[SOLD_CHANGE] == 0
    assert result.counts[NEW] == 0
    saved = decode_result(encode_result(result))
    again = detect_property_changes(rows, [prop], source_reference="fictional", previous=saved.state)
    assert not again.new_events and not again.observed_new_events
    history = again.state.source_states[prop["id"]]["source_history"]
    assert len(history) == 1 and next(iter(history.values()))["closing_verified"] is False
    assert "fictional-protected" not in json.dumps(encode_result(again))
    assert prop == before and result.records_written == result.external_actions_started == 0


def test_new_period_never_reuses_old_sale_clock_and_repeat_preserves_current_clock():
    rows = pair()
    prop = property_record(availability="Sold / Unavailable", listed_at="2020-01-01")
    previous = {prop["id"]: {"status": "sold / unavailable", "marketing_status": "yellow", "marketing_observed_since": "2020-01-01"}}
    first = observe_inventory(rows, [prop], previous, checked_at="2026-09-01")
    again = observe_inventory(rows[::-1], [prop], first, checked_at="2026-09-02")
    assert again[prop["id"]]["marketing_observed_since"] == "2026-09-01"
    item = inventory_items([prop], again, today=date(2026, 9, 11))[0]
    assert item["days_active"] == 10 and "tracked" in item["age_basis"]
    assert len(stale_checkpoint([prop], again, today=date(2026, 9, 11))["attention"]) == 1
    white = observe_inventory([replace(rows[0], marketing_status="white"), rows[1]], [prop], again, checked_at="2026-09-12")
    assert inventory_items([prop], white)[0]["days_active"] is None


def test_disappearing_current_row_leaving_old_history_is_review_only():
    rows = pair()
    prop = property_record(source="cfh-google-sheet", sync_metadata={"source_reference_hash": "fictional"})
    first = detect_property_changes(rows, [prop], source_reference="fictional")
    missing = detect_property_changes([rows[1]], [prop], source_reference="fictional", previous=first.state)
    assert missing.counts[MISSING] == 1 and missing.counts[SOLD_CHANGE] == 0
    obs = observe_inventory(rows, [prop], checked_at="2026-09-01")
    absent = observe_inventory([rows[1]], [prop], obs, checked_at="2026-09-02")
    assert absent[prop["id"]]["status"] == "Needs review"
    assert not inventory_items([prop], absent)
