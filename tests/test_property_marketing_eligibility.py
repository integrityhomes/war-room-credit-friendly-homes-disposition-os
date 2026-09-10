import copy
from dataclasses import replace

import pytest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.property_marketing_eligibility import marketing_checkpoint_preview
from cfh_disposition.property_sync_preview import NEW, REVIEW, compare_properties


@pytest.mark.parametrize("reason", ["Monthly insurance must be a number.", "Bedrooms must be a number.",
    "Square feet must be a number.", "Last update needs review because its date format was not recognized."])
def test_details_do_not_block_marketing_but_still_block_import(reason):
    row = replace(source_row(), marketing_status="yellow", issues=(reason,))
    assert compare_properties([row], []).counts[REVIEW] == 1
    assert compare_properties([row], []).counts[NEW] == 0
    preview = marketing_checkpoint_preview([row], [property_record()], {}, observed_at="2026-09-10")
    assert preview["eligible_count"] == preview["missing_count"] == 1
    assert not preview["applied"] and preview["records_written"] == 0


def test_history_preservation_and_exact_existing_clock_preservation_without_writes():
    row = replace(source_row(), marketing_status="yellow")
    history = replace(row, tab="SOLD", row=99)
    prop = property_record()
    obs = {prop["id"]: {"status": "available", "marketing_status": "yellow", "marketing_observed_since": "2026-09-01"}}
    snapshot = copy.deepcopy(obs)
    result = marketing_checkpoint_preview([row, history], [prop], obs, observed_at="2026-09-10")
    assert result["preserved_count"] == 1 and result["missing_count"] == 0
    assert result["eligible"][0]["preserved_start"] == "2026-09-01"
    assert obs == snapshot
    returned = marketing_checkpoint_preview([row, history], [prop], {}, observed_at="2026-09-10")
    patch = returned["eligible"][0]["proposed_checkpoint_patch"]
    assert patch["marketing_observed_since"] == "2026-09-10"
    assert patch["historical_occurrences"] == (("SOLD", 99),)


@pytest.mark.parametrize("case", ["white", "unknown", "duplicate", "different-id", "no-canonical", "unknown-tab", "address"])
def test_identity_color_and_current_row_safety_remain_required(case):
    row = replace(source_row(), marketing_status="yellow")
    rows, props = [row], [property_record()]
    if case in {"white", "unknown"}:
        rows = [replace(row, marketing_status=case)]
    elif case == "duplicate":
        rows.append(replace(row, row=99))
    elif case == "different-id":
        rows = [replace(row, external_id="other")]
        props = [property_record(external_id="existing")]
    elif case == "no-canonical":
        props = []
    elif case == "unknown-tab":
        rows = [replace(row, tab="Unknown")]
    else:
        rows = [replace(row, issues=("Address is incomplete or ambiguous; verify.",))]
    assert marketing_checkpoint_preview(rows, props, {}, observed_at="2026-09-10")["eligible_count"] == 0
