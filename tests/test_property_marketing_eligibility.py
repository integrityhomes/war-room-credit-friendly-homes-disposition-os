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


@pytest.mark.parametrize("warning", ["Fair cash value must be a number.", "Assessed value must be a number.", "Monthly payment must be a number."])
def test_identity_and_yellow_age_without_optional_availability_projection(warning):
    from datetime import date

    from cfh_disposition.corepilot_inventory import inventory_items, observe_inventory

    original = source_row()
    fields = {k: v for k, v in original.fields.items() if k in {"address", "city", "state", "zip", "zip_code"}}
    row = replace(original, fields=fields, marketing_status="yellow", issues=(warning,))
    prop = property_record()
    source_before = copy.deepcopy(row)
    start = "2030-01-01T00:00:00+00:00"
    first = observe_inventory([row], [prop], checked_at=start)
    pid = prop["id"]
    assert first[pid]["marketing_observed_since"] == start
    for at in ("2030-01-01T02:00:00+00:00", "2030-01-01T04:00:00+00:00"):
        first = observe_inventory([row], [prop], first, checked_at=at)
        assert first[pid]["marketing_observed_since"] == start
    for day, priority in ((11, "Needs attention"), (15, "Higher priority"), (22, "Urgent disposition review")):
        item = inventory_items([prop], first, today=date(2030, 1, day))[0]
        assert item["days_active"] == day - 1 and item["priority"] == priority
    for stopped_row in (replace(row, marketing_status="white"),
                        replace(row, fields={**fields, "availability": "Sold / Unavailable"}),
                        replace(row, tab="SOLD")):
        stopped = observe_inventory([stopped_row], [prop], first, checked_at="2030-02-01T00:00:00+00:00")
        assert not stopped[pid]["marketing_observed_since"]
        returned = observe_inventory([row], [prop], stopped, checked_at="2030-02-02T00:00:00+00:00")
        assert returned[pid]["marketing_observed_since"] == "2030-02-02T00:00:00+00:00"
        assert returned[pid]["marketing_restarted"]
    for invalid in ([row, replace(row, row=999)], [replace(row, marketing_status="unknown")], [replace(row, tab="Unverified tab")]):
        result = observe_inventory(invalid, [prop], checked_at=start)
        assert not result.get(pid, {}).get("marketing_observed_since")
    assert row == source_before and "availability" not in row.fields
