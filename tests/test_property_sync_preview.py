import copy
import json
from types import SimpleNamespace

import pytest

from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues
from cfh_disposition.property_sync_preview import (
    INVENTORY_TABS,
    MISSING,
    NEW,
    OTHER,
    PRICE,
    REVIEW,
    SOLD,
    STATUS,
    TERMS,
    SheetProperty,
    compare_properties,
    read_canonical_records,
    regional_sheet_properties,
    sheet_address_parts,
)


def property_record(**updates):
    return {"id": "fictional-property", "address": "101 Example Lane", "city": "Example City", "state": "IL", "zip": "60000",
            "asking_or_sale_price": "100000", "monthly_payment": "900", "availability": "Available", **updates}


def source_row(**updates):
    return SheetProperty(INVENTORY_TABS[0], 1, property_record(**updates))


def worksheets(row=None, extra=None):
    row = row or ["101 Example Lane, Example City, IL 60000", "", "3", "2", "1200", "5000", "900", "100000"]
    header = ["Property", "Lock box code", "Beds", "Baths", "Sq Ft", "Down Payment", "Monthly", "Sales Price"]
    return [ReadOnlyWorksheetValues(tab, [header, *([row] if tab == INVENTORY_TABS[0] else (extra or {}).get(tab, []))]) for tab in INVENTORY_TABS]


def test_new_property_is_a_proposal_without_creating_a_deal_or_record():
    rows = [source_row()]
    before = copy.deepcopy(rows)
    result = compare_properties(rows, [])
    assert result.counts[NEW] == 1
    assert result.items[0].property_id == ""
    assert result.items[0].linked_deals == ()
    assert result.records_written == result.external_actions_started == 0
    assert rows == before


@pytest.mark.parametrize(("field", "value", "category"), [
    ("asking_or_sale_price", "110000", PRICE), ("monthly_payment", "950", TERMS),
    ("availability", "Pending", STATUS), ("bedrooms", 4, OTHER),
])
def test_field_changes_have_correct_categories_and_before_after(field, value, category):
    records = [property_record()]
    before = copy.deepcopy(records)
    result = compare_properties([source_row(**{field: value})], records)
    assert result.items[0].categories == (category,)
    change = result.items[0].changes[0]
    assert change.field == field and change.proposed == str(value)
    assert records == before


def test_sold_is_explicit_and_missing_never_implies_sold():
    result = compare_properties([source_row(availability="Sold / Unavailable")], [property_record(), property_record(id="absent", address="202 Fiction Lane")])
    assert result.counts[SOLD] == result.counts[STATUS] == result.counts[MISSING] == 1
    assert result.items[1].categories == (MISSING,)
    assert result.items[1].changes == ()


def test_formatting_and_sheet_metadata_do_not_create_changes():
    row = source_row(address="101 EXAMPLE Lane, Example City, IL 60000", asking_or_sale_price="$100,000.00", monthly_payment="900.00", source_updated_at="2026-09-09")
    result = compare_properties([row], [property_record()])
    assert result.items[0].categories == ()


def test_external_id_preferred_and_existing_deal_link_preserved():
    row = SheetProperty("Virginia", 9, property_record(), external_id="stable-example")
    result = compare_properties([row], [property_record(external_id="stable-example")], [{"id": "existing-deal", "links": {"property_id": "fictional-property"}}])
    assert result.items[0].match_method == "External ID"
    assert result.items[0].linked_deals == ("existing-deal",)


@pytest.mark.parametrize("kind", ["sheet_address", "sheet_id", "crm_address", "crm_id", "conflicting_id", "changed_address"])
def test_ambiguous_identity_never_proposes_a_duplicate(kind):
    rows = [SheetProperty("Virginia", 1, property_record(), "source-example")]
    records = [property_record(external_id="source-example")]
    if kind == "sheet_address":
        rows.append(source_row())
    elif kind == "sheet_id":
        rows.append(SheetProperty("SOLD", 2, property_record(address="202 Fiction Lane"), "source-example"))
    elif kind == "crm_address":
        records.append(property_record(id="second", external_id="other-example"))
    elif kind == "crm_id":
        records.append(property_record(id="second", address="202 Fiction Lane", external_id="source-example"))
    elif kind == "conflicting_id":
        records[0]["external_id"] = "other-example"
    else:
        records[0]["address"] = "202 Fiction Lane"
    result = compare_properties(rows, records)
    assert result.counts[REVIEW] >= 1
    assert result.counts[NEW] == 0


def test_blank_field_change_requires_review():
    result = compare_properties([source_row(monthly_payment=None)], [property_record()])
    assert TERMS in result.items[0].categories
    assert REVIEW in result.items[0].categories


def test_malformed_source_prevents_false_missing_claims():
    row = SheetProperty("Virginia", 4, {"address": "Unrecognized source row"}, issues=("Invalid source",))
    result = compare_properties([row], [property_record()])
    assert result.counts[MISSING] == result.counts[NEW] == 0
    assert result.counts[REVIEW] == 2


def test_regional_adapter_uses_cache_only_for_reliable_identity():
    sheets = worksheets()
    sheets.append(ReadOnlyWorksheetValues("_REIBB_CACHE", [
        ["external_id", "address", "city", "state", "zip", "sales_price"],
        ["stable-example", "101 Example Lane", "Example City", "IL", "60000", "999999"],
        ["cache-only", "999 Fiction Lane", "Example City", "IL", "60000", "999999"],
    ]))
    rows = regional_sheet_properties(sheets, "fictional-sheet")
    assert len(rows) == 1
    assert rows[0].external_id == "stable-example"
    assert rows[0].fields["asking_or_sale_price"] == "100000"
    sheets[-1] = ReadOnlyWorksheetValues("_REIBB_CACHE", [*sheets[-1], sheets[-1][1]])
    assert regional_sheet_properties(sheets, "fictional-sheet")[0].external_id == ""


def test_restriction_tabs_and_unknown_tabs_do_not_launch_inventory():
    row = ["202 Fiction Lane, Example City, IL 60000", "", "3", "2", "1200", "5000", "900", "100000"]
    sheets = worksheets(extra={"SOLD": [row]})
    sheets.append(ReadOnlyWorksheetValues("Sheet36", [row]))
    rows = regional_sheet_properties(sheets, "fictional-sheet")
    assert len(rows) == 2
    assert rows[1].fields["availability"] == "Sold / Unavailable"
    sheets[-2] = ReadOnlyWorksheetValues("DO NOT SELL LIST", [sheets[0][0], row])
    rows = regional_sheet_properties(sheets, "fictional-sheet")
    assert rows[-1].fields["availability"] == "Paused"


def test_incomplete_sheet_read_fails_instead_of_reporting_missing():
    with pytest.raises(ValueError, match="Inventory tabs are missing"):
        regional_sheet_properties(worksheets()[:-1], "fictional-sheet")


def test_live_style_repeated_headers_and_swapped_payment_columns():
    sheets = worksheets()
    header = ["Fictional region", "Lock box code", "Beds", "Baths", "Sq Ft", "Monthly", "Down Payment", "Sales Price", "Date Added to Sheet"]
    row = ["202 Fiction Lane, Example City, IL 60000", "", "3", "2", "1200", "800", "6000", "90000", "9/9/2026"]
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [*sheets[0], header, row])
    rows = regional_sheet_properties(sheets, "fictional-sheet")
    assert len(rows) == 2
    assert rows[1].fields["monthly_payment"] == "800"
    assert rows[1].fields["down_payment"] == "6000"
    assert not rows[1].issues


def test_unconfirmed_column_layout_never_invents_new_property():
    sheets = worksheets()
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], sheets[0][1:])
    result = compare_properties(regional_sheet_properties(sheets, "fictional-sheet"), [])
    assert result.counts[NEW] == 0
    assert result.counts[REVIEW] == 1


def test_invalid_numeric_fact_retains_address_match_and_blocks_missing():
    sheets = worksheets(row=["101 Example Lane, Example City, IL 60000", "", "3", "2", "1200", "5000", "unclear", "100000"])
    result = compare_properties(regional_sheet_properties(sheets, "fictional-sheet"), [property_record()])
    assert len(result.items) == 1 and result.items[0].property_id == "fictional-property"
    assert result.counts[REVIEW] == 1 and result.counts[MISSING] == 0


@pytest.mark.parametrize("address", [
    "101 Example Lane Example City IL 60000",
    "101 Example Lane, Example City IL 60000",
    "101 Example Lane\nExample City, IL 60000",
])
def test_complete_address_punctuation_variants_keep_explicit_components(address):
    parts = sheet_address_parts(address)
    assert parts == {"address": "101 Example Lane", "city": "Example City", "state": "IL", "zip_code": "60000"}
    sheets = worksheets(row=[address, "", "3", "2", "1200", "5000", "900", "100000"])
    result = compare_properties(regional_sheet_properties(sheets, "fictional-sheet"), [])
    assert result.counts[NEW] == 1


@pytest.mark.parametrize("address", [
    "101 Example Lane Example City IL", "101 Example Lane IL 60000", "101 Example Example City IL 60000",
    "101 Example St Charles Ave Example City IL 60000", "101 Example Lane NW Example City IL 60000",
    "101 Example Lane Apt 2 Example City IL 60000",
])
def test_incomplete_or_ambiguous_addresses_do_not_guess_city_or_identity(address):
    sheets = worksheets(row=[address, "", "3", "2", "1200", "5000", "900", "100000"])
    rows = regional_sheet_properties(sheets, "fictional-sheet")
    assert any("Address is incomplete or ambiguous" in issue for issue in rows[0].issues)
    assert not any("Stable source record ID" in issue for issue in rows[0].issues)
    assert compare_properties(rows, []).counts[NEW] == 0


def test_only_confirmed_single_cell_sections_are_excluded():
    sheets = worksheets()
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [
        ["Decatur"], ["Available properties"], ["SOLD"], *sheets[0],
        ["Unconfirmed label"], ["Decatur", "Unconfirmed second cell"],
    ])
    rows = regional_sheet_properties(sheets, "fictional-sheet")
    assert len(rows) == 3
    assert sum(bool(row.issues) for row in rows) == 2


@pytest.mark.parametrize("marker", ["", "N/A", "NA", "n/a", " Not Applicable ", "not-applicable"])
def test_explicit_numeric_absence_is_not_zero_or_invalid(marker):
    sheets = worksheets(row=["101 Example Lane, Example City, IL 60000", "", marker, marker, marker, marker, marker, "100000"])
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [[*sheets[0][0], "Insurance"], [*sheets[0][1], marker]])
    row = regional_sheet_properties(sheets, "fictional-sheet")[0]
    assert not row.issues
    for field in ("bedrooms", "bathrooms", "square_feet", "down_payment", "monthly_payment", "monthly_insurance"):
        assert row.fields[field] is None


@pytest.mark.parametrize(("column", "value"), [
    (2, "2 (3)"), (2, "1/1"), (2, "1 (potential 3 bed)"), (3, "1/1"),
    (6, "725 (PIT only)"), (6, "$2000 +$500 fee"), (6, "950 PITI"),
    (6, "$995 per month plus insurance"), (8, "Buyer responsibility"),
    (8, "$711 ($59.25 monthly)"), (8, "TBD"), (8, "Buyer gets own insurance"),
])
def test_ambiguous_room_counts_and_payment_notes_still_require_review(column, value):
    sheets = worksheets()
    values = [*sheets[0][1], "100"]
    values[column] = value
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [[*sheets[0][0], "Insurance"], values])
    result = compare_properties(regional_sheet_properties(sheets, "fictional-sheet"), [])
    assert result.counts[REVIEW] == 1
    assert result.counts[NEW] == 0


def test_purchase_price_does_not_become_sales_price_and_sold_is_not_closing_proof():
    sheets = worksheets()
    header = [*sheets[0][0][:-1], "Purchase Price"]
    sheets[0] = ReadOnlyWorksheetValues(INVENTORY_TABS[0], [header, sheets[0][1]])
    result = compare_properties(regional_sheet_properties(sheets, "fictional-sheet"), [])
    assert result.counts[REVIEW] == 1
    assert "purchase price is not assumed" in result.items[0].reason
    assert any("does not independently verify a closing" in warning for warning in result.warnings)


def test_review_reason_counts_count_each_row_once_per_reason():
    rows = [SheetProperty("Virginia", 1, property_record(), issues=("Unclear amount.", "Unclear amount.")),
            SheetProperty("Virginia", 2, property_record(address="202 Fiction Lane"), issues=("Unclear amount.",))]
    assert compare_properties(rows, []).review_reason_counts["Unclear amount."] == 2


def test_canonical_reader_paginates_and_exposes_no_writes():
    calls = []

    class Bucket:
        def list(self, entity, options):
            calls.append(options["offset"])
            return [{"name": f"{n}.json"} for n in range(500)] if options["offset"] == 0 else [{"name": "last.json"}]

        def download(self, path):
            return json.dumps({"id": path}).encode()

    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: Bucket()))
    assert len(read_canonical_records(client, "properties")) == 501
    assert calls == [0, 500]


def test_canonical_read_failure_is_not_an_empty_crm():
    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: SimpleNamespace(list=lambda *args: None)))
    with pytest.raises(ValueError):
        read_canonical_records(client, "properties")
