from dataclasses import replace
from datetime import date

import pytest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.corepilot_inventory import inventory_items, observe_inventory, stale_checkpoint
from cfh_disposition.google_property_marketing import attach_highlights, highlight_status, read_row_highlights
from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues


def observed(color, previous=None, *, at="2026-09-01", availability="Available", listed_at=None):
    prop = property_record(**({"listed_at": listed_at} if listed_at else {}))
    row = replace(source_row(availability=availability), marketing_status=color)
    return prop, observe_inventory([row], [prop], previous, checked_at=at)


def test_white_never_ages_even_with_old_listed_date():
    prop, state = observed("white", listed_at="2020-01-01")
    item = inventory_items([prop], state, today=date(2026, 10, 1))[0]
    assert item["days_active"] is None and not item["priority"]
    assert item["age_basis"] == "Not ready to market"


def test_white_yellow_white_yellow_starts_distinct_marketing_periods():
    prop, white = observed("white", listed_at="2020-01-01")
    prop, yellow = observed("yellow", white, at="2026-09-05", listed_at="2020-01-01")
    item = inventory_items([prop], yellow, today=date(2026, 9, 15))[0]
    assert item["days_active"] == 10 and item["priority"] == "Needs attention"
    assert item["age_basis"] == "CommandCore has tracked this property as marketed"
    prop, white_again = observed("white", yellow, at="2026-09-16")
    item = inventory_items([prop], white_again, today=date(2026, 10, 1))[0]
    assert item["days_active"] is None and item["status"] == "available"
    prop, again = observed("yellow", white_again, at="2026-09-20", listed_at="2020-01-01")
    assert inventory_items([prop], again, today=date(2026, 9, 21))[0]["days_active"] == 1


def test_yellow_sold_stops_and_repeat_checks_are_idempotent():
    prop, yellow = observed("yellow")
    first = stale_checkpoint([prop], yellow, today=date(2026, 9, 11))
    prop, repeated = observed("yellow", yellow, at="2026-09-11T02:00:00Z")
    second = stale_checkpoint([prop], repeated, first, today=date(2026, 9, 11))
    assert len(first["attention"]) == len(second["attention"]) == 1 and not second["new_ids"]
    prop, sold = observed("yellow", repeated, availability="Sold / Unavailable")
    assert inventory_items([prop], sold, today=date(2026, 10, 1)) == []
    assert prop["availability"] == "Available"  # Source evidence never writes the canonical record.


def test_legacy_active_observation_and_unknown_color_cannot_age_marketing():
    prop = property_record(listed_at="2020-01-01")
    legacy = {prop["id"]: {"status": "available", "active_observed_since": "2020-01-01"}}
    assert inventory_items([prop], legacy)[0]["days_active"] is None
    prop, unknown = observed("unknown", legacy)
    assert inventory_items([prop], unknown)[0]["days_active"] is None


def test_sold_return_to_yellow_starts_new_period_and_two_hour_checks_preserve_it():
    prop, yellow = observed("yellow", listed_at="2020-01-01")
    prop, sold = observed("yellow", yellow, at="2026-09-02", availability="Sold / Unavailable")
    assert sold[prop["id"]]["marketing_observed_since"] == ""
    prop, returned = observed("yellow", sold, at="2026-09-05T00:00:00Z", listed_at="2020-01-01")
    for hour in (2, 4, 6):
        prop, returned = observed("yellow", returned, at=f"2026-09-05T{hour:02}:00:00Z", listed_at="2020-01-01")
        assert returned[prop["id"]]["marketing_observed_since"] == "2026-09-05T00:00:00Z"
    item = inventory_items([prop], returned, today=date(2026, 9, 6))[0]
    assert item["days_active"] == 1
    assert item["age_basis"] == "CommandCore has tracked this property as marketed"


def test_initial_yellow_can_use_explicit_verified_listed_date():
    prop, yellow = observed("yellow", listed_at="2026-08-01")
    item = inventory_items([prop], yellow, today=date(2026, 9, 1))[0]
    assert item["days_active"] == 31 and item["age_basis"] == "Actively marketed"


@pytest.mark.parametrize("rgb,expected", [({"red": 1, "green": 1}, "yellow"), ({"red": 1, "green": 1, "blue": 1}, "white"),
                                        ({"green": 1}, "unknown"), ({"red": 1}, "unknown")])
def test_effective_colors_are_not_guessed(rgb, expected):
    assert highlight_status({"effectiveFormat": {"backgroundColorStyle": {"rgbColor": rgb}}}) == expected
    assert highlight_status({"effectiveFormat": {"backgroundColor": rgb}}) == expected
    assert highlight_status({}) == "unknown"


def test_bounded_read_validates_identity_and_only_uses_get():
    class Session:
        def get(self, url, params, timeout):
            assert not url.endswith("batchUpdate") and timeout == 120
            assert ("ranges", "'Fictional region'!A1:A1") in params
            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"sheets": [{"properties": {"title": "Fictional region"}, "data": [{"rowData": [{"values": [
                        {"formattedValue": "101 Example Lane", "effectiveFormat": {"backgroundColor": {"red": 1, "green": 1}}}]}]}]}]}
            return Response()

    highlights = read_row_highlights(Session(), "fictional", [ReadOnlyWorksheetValues("Fictional region", [["101 Example Lane"]])])
    assert highlights == {("Fictional region", 1): "yellow"}
    row = replace(source_row(), tab="Fictional region", row=1)
    assert attach_highlights([row], highlights)[0].marketing_status == "yellow"
    with pytest.raises(ValueError, match="changed during"):
        read_row_highlights(Session(), "fictional", [ReadOnlyWorksheetValues("Fictional region", [["999 Different Lane"]])])
