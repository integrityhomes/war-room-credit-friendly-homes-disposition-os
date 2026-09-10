from types import SimpleNamespace

import pytest
from test_property_sync_preview import worksheets

from cfh_disposition.google_property_marketing import attach_highlights, read_row_highlights
from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues
from cfh_disposition.property_baseline import load_baseline_source
from cfh_disposition.property_source_coverage import coverage_lines, source_coverage
from cfh_disposition.property_sync_preview import INVENTORY_TABS, REVIEW, compare_properties, regional_sheet_properties

HEADER = ["Property", "Beds", "Baths", "Sales price", "Monthly", "Down payment"]
FIRST = ["101 Example Lane, Example City, IL 60000", "3", "2", "100000", "900", "5000"]
OTHER = ["202 Fictional Lane, Sample City, MO 63000", "2", "1", "90000", "800", "4000"]


def test_all_tabs_sections_layouts_and_duplicate_protection():
    sheets = list(worksheets())
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [HEADER, FIRST, [], ["Properties"],
        ["Monthly", "Property", "Sales price", "Beds", "Baths"],
        ["800", OTHER[0], "90000", "2", "1"], [], HEADER, FIRST])
    sheets.append(ReadOnlyWorksheetValues("Later fictional region", [HEADER, OTHER]))
    sheets.append(ReadOnlyWorksheetValues("Empty notes", [["Notes"], [], ["Private instructions"]]))
    rows = regional_sheet_properties(sheets, "fictional")
    assert len(rows) == 4
    assert rows[1].fields["state"] == "MO"
    assert rows[1].fields["monthly_payment"] == "800"
    assert rows[-1].tab == "Later fictional region"
    assert any("availability has not been verified" in issue for issue in rows[-1].issues)
    preview = compare_properties(rows, [])
    assert all(REVIEW in item.categories for item in preview.items)
    assert all("Duplicate" in item.reason for item in preview.items)
    coverage = source_coverage(sheets, rows)
    assert coverage["candidate_rows"] == 4
    assert coverage["unique_complete_addresses"] == 2
    assert coverage["duplicate_address_rows"] == 2
    assert coverage["tab_count"] == len(sheets)
    assert coverage["tabs"][0]["header_rows"] == [1, 5, 8]


def test_highlights_follow_later_explicit_address_column_and_unknown_stays_unknown():
    ws = ReadOnlyWorksheetValues("Later region", [HEADER, FIRST, [],
        ["Beds", "Address", "Baths", "Sales price"], ["2", OTHER[0], "1", "90000"]])
    grids = []
    for index, values in enumerate(ws):
        grids.append({"values": [{"formattedValue": value, "effectiveFormat": {"backgroundColor":
            {"red": 1, "green": 1} if index == 4 and col == 1 else {"red": 1, "green": 1, "blue": 1}}}
            for col, value in enumerate(values)]})
    class Session:
        def get(self, url, params, timeout):
            assert ("ranges", "'Later region'!A1:B5") in params
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"sheets": [
                {"properties": {"title": ws.tab_name}, "data": [{"rowData": grids}]}]})
    statuses = read_row_highlights(Session(), "fictional", [ws])
    assert statuses[ws.tab_name, 5] == "yellow"
    assert statuses[ws.tab_name, 2] == "white"


def test_dynamic_reader_discovers_late_tab_and_reads_every_range(monkeypatch):
    from cfh_disposition import google_property_runtime_bridge as bridge
    names = (*INVENTORY_TABS, "_REIBB_CACHE", "New fictional tab")
    calls = []
    class Session:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url, params, timeout):
            calls.append(url.rsplit("/", 1)[-1])
            if url.endswith("batchGet"):
                assert len([p for p in params if p[0] == "ranges"]) == len(names)
                payload = {"valueRanges": [{"values": [HEADER, OTHER] if n == names[-1] else []} for n in names]}
            else:
                payload = {"sheets": [{"properties": {"title": n, "hidden": True}} for n in names]}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Session)
    monkeypatch.setattr(bridge, "resolve_read_only_google_access", lambda *a: (object(), "fictional"))
    rows, source = load_baseline_source({})
    assert len(rows) == 1 and rows[0].tab == names[-1] and rows[0].issues
    assert rows.coverage["tab_count"] == len(names)
    assert len(calls) == 2


@pytest.mark.parametrize("color", ["yellow", "white", "unknown"])
def test_source_totals_are_separate_from_validation_and_sold_precedence(color):
    sheets = list(worksheets())
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [HEADER, [FIRST[0], "ambiguous", *FIRST[2:]]])
    sold = next(i for i, ws in enumerate(sheets) if ws.tab_name == "SOLD")
    sheets[sold] = ReadOnlyWorksheetValues("SOLD", [HEADER, OTHER])
    rows = attach_highlights(regional_sheet_properties(sheets, "fictional"), {(INVENTORY_TABS[0], 2): color, ("SOLD", 2): "white"})
    coverage = source_coverage(sheets, rows)
    assert coverage["candidate_rows"] == 2 and coverage["sold_candidate_rows"] == 1
    assert coverage["source_colors"][color] >= 1
    assert rows[0].issues
    assert "not the current marketed-property count" in coverage_lines(coverage)[0]
    assert "eligible for marketing-age" not in coverage_lines(coverage)[0]
    assert all("lockbox" not in str(value).lower() for value in coverage.values())


def test_confirmed_support_list_excluded_but_changed_layout_not_silently_dropped():
    from cfh_disposition.property_sync_preview import worksheet_classification
    sheets = list(worksheets())
    index = next(i for i, ws in enumerate(sheets) if ws.tab_name == "DO NOT SELL LIST")
    sheets[index] = ReadOnlyWorksheetValues("DO NOT SELL LIST", [["DO NOT SELL TO"], ["Fictional Person"]])
    assert worksheet_classification(sheets[index]) == "support/cache/system"
    assert not any(row.tab == "DO NOT SELL LIST" for row in regional_sheet_properties(sheets, "fictional"))
    sheets[index] = ReadOnlyWorksheetValues("DO NOT SELL LIST", [["DO NOT SELL TO"], HEADER, OTHER])
    assert worksheet_classification(sheets[index]) == "unknown / needs review"
    assert any(row.tab == "DO NOT SELL LIST" for row in regional_sheet_properties(sheets, "fictional"))


def test_status_counts_exclude_sold_white_and_unclassified_yellow():
    from cfh_disposition.property_source_coverage import reconcile_coverage
    sheets = list(worksheets())
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [HEADER, FIRST])
    sold = next(i for i, ws in enumerate(sheets) if ws.tab_name == "SOLD")
    sheets[sold] = ReadOnlyWorksheetValues("SOLD", [HEADER, OTHER])
    sheets.append(ReadOnlyWorksheetValues("Unknown purpose", [HEADER, OTHER]))
    rows = attach_highlights(regional_sheet_properties(sheets, "fictional"), {
        (INVENTORY_TABS[0], 2): "white", ("SOLD", 2): "white", ("Unknown purpose", 2): "yellow"})
    cov = source_coverage(sheets, rows)
    assert cov["source_colors"] == {"white": 2, "yellow": 1}
    assert cov["lifecycle_candidate_rows"] == {"white": 1, "sold": 1, "unknown": 1}
    assert cov["legitimate_unique_complete_addresses"] == 2
    assert cov["lifecycle_unique_complete_addresses"]["sold"] == 1
    assert reconcile_coverage(cov, rows, [rows[0].fields])["source_unique_addresses_in_canonical"] == 1
    import json
    assert "Example Lane" not in json.dumps(cov)


def test_header_recognition_shared_by_parser_and_formatting_scan():
    from cfh_disposition.property_source_coverage import address_columns
    ws = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [HEADER, FIRST,
        ["Property", "Notes", "Photos"], OTHER])
    sheets = list(worksheets())
    sheets[0] = ws
    rows = regional_sheet_properties(sheets, "fictional")
    assert source_coverage(sheets, rows)["tabs"][0]["header_blocks"] == 1
    assert set(address_columns(ws).values()) == {0}


@pytest.mark.parametrize("address", [
    "101 Example Lane, Example City, IL. 60000",
    "101 Example Lane, Example City, IL60000",
    "101 Example Lane, Example City, Illinois 60000",
    "101 Example Lane | Example City, IL 60000",
])
def test_address_recovery_uses_only_explicit_components(address):
    from cfh_disposition.property_sync_preview import sheet_address_parts
    assert sheet_address_parts(address, verified_format_recovery=True) == {"address": "101 Example Lane", "city": "Example City", "state": "IL", "zip_code": "60000"}


@pytest.mark.parametrize("address", ["101 Example Lane, Example City, IL", "101 Example Lane, Example City, IL 6000", "101 Example Lane", "101 Example Lane, Example City 60000"])
def test_address_recovery_never_supplies_missing_components(address):
    from cfh_disposition.property_sync_preview import sheet_address_parts
    assert not all(sheet_address_parts(address, verified_format_recovery=True).values())


def test_full_state_name_does_not_match_only_part_of_a_compound_state():
    from cfh_disposition.property_sync_preview import sheet_address_parts
    assert sheet_address_parts("101 Example Lane, Example City, West Virginia 25000", verified_format_recovery=True)["state"] == "WV"


@pytest.mark.parametrize("field,value,expected", [
    ("square_feet", "1200 sq ft", "1200"),
    ("monthly_insurance", "$ 55.00 / month", "55.00"),
    ("total_monthly_payment", "900/month", "900"),
    ("total_monthly_payment", "900 PITI", "900"),
    ("total_monthly_payment", "$900.50 piti", "900.50"),
    ("total_monthly_payment", "900 PIT", "900 PIT"),
    ("total_monthly_payment", "900 PITI plus fee", "900 PITI plus fee"),
    ("monthly_principal_interest", "900 PITI", "900 PITI"),
    ("monthly_insurance", "55 plus 20 fee", "55 plus 20 fee"),
    ("monthly_insurance", "Buyer responsibility", "Buyer responsibility"),
    ("total_monthly_payment", "900 (PIT only)", "900 (PIT only)"),
    ("square_feet", "1200 (900 SQFT)", "1200 (900 SQFT)"),
    ("beds", "3 (4)", "3 (4)"),
])
def test_numeric_units_never_strip_qualifications(field,value,expected):
    from cfh_disposition.property_sync_preview import explicit_numeric_units
    assert explicit_numeric_units(field,value) == expected


def test_verified_format_recovery_requires_opt_in_and_preserves_scheduled_input():
    from cfh_disposition.property_sync_preview import sheet_address_parts
    address = "101 Example Lane, Example City, IL60000"
    sheets = list(worksheets())
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [HEADER, [address, *FIRST[1:]]])
    assert not all(sheet_address_parts(address).values())
    assert regional_sheet_properties(sheets, "fictional")[0].issues
    recovered = regional_sheet_properties(sheets, "fictional", verified_format_recovery=True)
    assert not recovered[0].issues
    assert recovered[0].fields["city"] == "Example City"
