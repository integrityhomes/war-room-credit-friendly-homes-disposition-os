import copy
import json
from dataclasses import replace
from pathlib import Path

from streamlit.testing.v1 import AppTest
from test_property_sync_preview import worksheets

from cfh_disposition.property_import_reconciliation import build_current_inventory_candidates, build_import_reconciliation
from cfh_disposition.property_source_fields import read_source_fields
from cfh_disposition.property_sync_preview import regional_sheet_properties


def rows():
    return [replace(r, marketing_status="yellow") for r in regional_sheet_properties(worksheets(), "fictional")]


def test_one_current_property_with_history_yellow_first_and_no_writes():
    current = rows()[0]
    history = replace(current, tab="SOLD", row=55)
    white = replace(current, row=9, marketing_status="white", fields={**current.fields, "address": "202 Fiction Lane"})
    source = [white, history, current]
    before = copy.deepcopy(source)
    result = build_import_reconciliation(source, [])
    assert result["total_missing"] == 2 and result["total_ready"] == 2
    assert result["properties"][0]["classification"] == "Yellow"
    assert result["properties"][0]["historical_occurrences"][0]["closing_verified"] is False
    assert source == before and result["records_written"] == 0 and not result["import_enabled"]


def test_valid_insurance_text_is_not_a_numeric_blocker_but_ambiguous_rooms_remain_blocked():
    current = rows()[0]
    evidence = read_source_fields(["Property", "Insurance"], ["Fictional address", "Buyer responsible"])
    insured = replace(current, issues=("Monthly insurance must be a number.",), source_fields=evidence)
    assert build_import_reconciliation([insured], [])["total_ready"] == 1
    ambiguous = replace(insured, issues=(*insured.issues, "Bedrooms must be a number."))
    result = build_import_reconciliation([ambiguous], [])
    assert result["yellow_missing"] == 1 and result["total_ready"] == 0
    assert result["properties"][0]["identity_verified"] and result["properties"][0]["marketing_verified"]


def test_duplicate_source_and_canonical_id_conflicts_never_ready():
    current = rows()[0]
    duplicate = build_import_reconciliation([current, replace(current, row=4)], [])
    assert duplicate["total_missing"] == 1 and duplicate["total_ready"] == 0 and duplicate["duplicate_conflict_count"] == 1
    prop = {**current.fields, "id": "canonical", "external_id": "source-x", "address": "303 Another Lane"}
    result = build_import_reconciliation([replace(current, external_id="source-x")], [prop])
    assert result["total_ready"] == 0 and result["properties"][0]["canonical_match"] == "canonical"


def test_canonical_yellow_clocks_are_read_only_and_codes_never_appear():
    current = rows()[0]
    prop = {**current.fields, "id": "canonical"}
    result = build_import_reconciliation([current], [prop])
    assert result["total_missing"] == 0 and result["yellow_canonical"] == 1 and len(result["missing_marketing_clocks"]) == 1
    secret = replace(current, fields={**current.fields, "lockbox_code": "SECRET-FIXTURE", "notes": "Use SECRET-FIXTURE"})
    result = build_import_reconciliation([secret], [])
    assert "SECRET-FIXTURE" not in json.dumps(result)
    assert result["properties"][0]["access_code_present"]


def test_actual_baseline_page_renders_new_preview_without_import_or_checkpoint_controls(monkeypatch):
    result = build_import_reconciliation(rows(), [])
    result["current_inventory"] = build_current_inventory_candidates(rows(), [], reconciliation=result)
    calls = []
    monkeypatch.setattr("cfh_disposition.property_import_reconciliation_ui.load_import_reconciliation", lambda secrets: calls.append("read") or result)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/53_CommandCore_Property_Baseline.py"))
    app.secrets["APP_PASSWORD"] = "fictional"
    app.session_state["authenticated"] = True
    app.run()
    app.button(key="build_missing_property_preview").click().run()
    assert not app.exception and calls == ["read"]
    assert app.button(key="missing_import_disabled").disabled
    assert app.radio(key="import_reconciliation_scope").value == "Current inventory only"
