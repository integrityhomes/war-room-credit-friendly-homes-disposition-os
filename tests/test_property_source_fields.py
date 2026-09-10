import json

import pytest
from test_property_sync_preview import worksheets

from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues
from cfh_disposition.property_source_fields import read_source_fields
from cfh_disposition.property_sync_preview import regional_sheet_properties


@pytest.mark.parametrize("header,raw,expected", [
    ("Owner / seller", "Fictional Owner LLC", "Fictional Owner LLC"),
    ("LLC / Trust Name", "Fictional Trust", "Fictional Trust"),
    ("Insurance", "Buyer to obtain own insurance", {"responsibility": "buyer", "amount": None}),
    ("Insurance", "Buyer responsible", {"responsibility": "buyer", "amount": None}),
    ("Insurance included", "Yes", True), ("Insurance", "$55", "55"),
    ("Asking price", "$100,000", "100000"), ("Purchase price", "$70,000", "70000"),
    ("Down payment", "5000", "5000"), ("Monthly", "925 PITI", "925"),
    ("Interest rate APR", "9.5%", "9.5"), ("Monthlytaxes", "60", "60"),
    ("Beds", "3", "3"), ("Baths", "1.5", "1.5"), ("Sq ft", "1200 sq ft", "1200"),
    ("Notes", "Needs inspection", "Needs inspection"), ("Last Update", "Fictional Person", "Fictional Person"),
])
def test_fields_preserve_raw_and_explicit_meaning(header, raw, expected):
    field = read_source_fields(["Property", header], ["Fictional address", raw])[1]
    assert field["raw"] == raw and field["normalized"] == expected and not field["review"]


@pytest.mark.parametrize("header,raw", [("Beds", "1/1"), ("Sq ft", "??"), ("Monthly", "925 PIT only"),
    ("Monthly payment principal", "800 plus fee"), ("New update date", "Fictional Person")])
def test_unclear_field_is_retained_and_reviewed(header, raw):
    field = read_source_fields(["Property", header], ["Fictional address", raw])[1]
    assert field["review"] and field["normalized"] is None and field["raw"] == raw


def test_lockbox_and_access_notes_are_protected_in_evidence():
    evidence = read_source_fields(["Property", "Lock box code", "Notes"], ["Fictional address", "SECRET-FIXTURE", "Use SECRET-FIXTURE"])
    assert "SECRET-FIXTURE" not in json.dumps(evidence)
    assert evidence[1]["raw"] == "[protected]"


def test_repeated_and_unknown_headers_do_not_silently_discard_cells():
    evidence = read_source_fields(["Property", "Insurance", "Insurance", "Special observation"], ["Fictional address", "55", "65", "Recorded text"])
    assert evidence[1]["review"] and evidence[2]["review"]
    assert evidence[3]["raw"] == "Recorded text" and evidence[3]["review"]


def test_real_adapter_preserves_other_facts_and_handles_later_reordered_sections():
    sheets = worksheets()
    headers = ["Property", "Beds", "Baths", "Sales price", "Insurance", "Owner", "Last Update", "Lockbox"]
    values = ["101 Example Lane, Example City, IL 60000", "3", "1", "100000", "Buyer responsible", "Fictional LLC", "Fictional Person", "SECRET-FIXTURE"]
    sheets[0] = ReadOnlyWorksheetValues(sheets[0].tab_name, [headers, values, [], list(reversed(headers)), list(reversed(values))])
    rows = regional_sheet_properties(sheets, "fictional")
    assert len(rows) == 2
    for row in rows:
        assert row.fields["bedrooms"] == 3
        assert row.fields["asking_or_sale_price"] == "100000"
        assert row.fields["seller_entity"] == "Fictional LLC"
        assert row.fields["lockbox_code"] == "SECRET-FIXTURE"
        assert "SECRET-FIXTURE" not in repr(row)
        assert "SECRET-FIXTURE" not in json.dumps(row.source_fields)
        detail = next(f for f in row.source_fields if f["field"] == "monthly_insurance")
        assert detail["normalized"]["responsibility"] == "buyer"
        assert row.issues  # Strict import gate stays separate from successful field reading.
