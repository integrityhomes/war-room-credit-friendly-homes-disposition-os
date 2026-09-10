from dataclasses import replace
from datetime import date, timedelta

import pytest
from test_property_sync_preview import property_record
from test_property_sync_preview import source_row as original_source_row

from cfh_disposition.corepilot_inventory import advise_property, observe_inventory, stale_checkpoint
from cfh_disposition.corepilot_inventory import inventory_items as actual_inventory_items
from cfh_disposition.corepilot_orchestrator import run_corepilot


def source_row(**changes):
    return replace(original_source_row(**changes), marketing_status="yellow")


def inventory_items(properties, observations=None, **kwargs):
    # Existing aging scenarios explicitly assume verified yellow formatting.
    if observations is None:
        observations = {p["id"]: {"marketing_status": "yellow"} for p in properties}
    return actual_inventory_items(properties, observations, **kwargs)


TODAY = date(2026, 9, 9)


def prop(age=None, **changes):
    return property_record(**({"listed_at": (TODAY - timedelta(days=age)).isoformat()} if age is not None else {}), **changes)


@pytest.mark.parametrize("age,priority", [(9, ""), (10, "Needs attention"), (14, "Higher priority"), (21, "Urgent disposition review")])
def test_verified_active_age_thresholds(age, priority):
    assert inventory_items([prop(age)], today=TODAY)[0]["priority"] == priority


def test_no_invented_age_or_generic_import_update_dates():
    p = prop(created_at="2020-01-01", source_updated_at="2020-01-01", sync_metadata={"observed_at": "2020-01-01"})
    item = inventory_items([p], today=TODAY)[0]
    assert item["days_active"] is None and not item["priority"] and item["days_since_change"] is None
    assert inventory_items([prop(20, availability="Sold / Unavailable")], today=TODAY) == []


def test_source_sold_removes_stale_and_returned_active_restarts_observed_lower_bound():
    p = prop(40)
    active = observe_inventory([source_row()], [p], checked_at="2026-08-01")
    assert inventory_items([p], active, today=TODAY)[0]["priority"]
    sold = observe_inventory([source_row(availability="Sold / Unavailable")], [p], active, checked_at="2026-09-08")
    assert not inventory_items([p], sold, today=TODAY)
    returned = observe_inventory([source_row()], [p], sold, checked_at="2026-09-09")
    item = inventory_items([p], returned, today=TODAY)[0]
    assert item["days_active"] == 0 and "tracked" in item["age_basis"]
    historical = prop(40, availability="Sold / Unavailable")
    first_return = observe_inventory([source_row()], [historical], checked_at="2026-09-09")
    assert inventory_items([historical], first_return, today=TODAY)[0]["days_active"] == 0


def test_repeated_checkpoints_keep_attention_without_duplicate_alerts():
    p = prop(21)
    observations = observe_inventory([source_row()], [p], checked_at="2026-09-09")
    first = stale_checkpoint([p], observations, today=TODAY)
    repeated = stale_checkpoint([p], observations, first, today=TODAY)
    assert len(first["new_ids"]) == 1 and repeated["new_ids"] == [] and len(repeated["attention"]) == 1


def test_duplicate_and_invalid_source_rows_excluded_and_missing_is_not_sold():
    p = prop(21)
    previous = observe_inventory([source_row()], [p], checked_at="2026-08-01")
    duplicated = observe_inventory([source_row(), source_row()], [p], previous, checked_at="2026-09-09")
    assert not inventory_items([p], duplicated, today=TODAY)
    missing = observe_inventory([], [p], previous, checked_at="2026-09-09")
    assert missing[p["id"]]["status"] == "Needs review"
    assert not inventory_items([p], missing, today=TODAY)


def test_meaningful_change_dates_require_observed_change():
    p = prop(21)
    first = observe_inventory([source_row()], [p], checked_at="2026-08-01")
    repeat = observe_inventory([source_row()], [p], first, checked_at="2026-08-20")
    assert not repeat[p["id"]]["last_change_observed_at"]
    changed = observe_inventory([source_row(monthly_payment="895")], [p], repeat, checked_at="2026-09-01")
    item = inventory_items([p], changed, today=TODAY)[0]
    assert item["days_since_change"] == 8


def test_advice_labels_missing_evidence_and_does_not_guess_price():
    p = prop(21)
    advice = advise_property(p, {}, inventory_items([p], today=TODAY)[0])
    assert any("Buyer-response" in x for x in advice["missing"])
    assert any("Marketing" in x for x in advice["missing"])
    assert advice["causes"] == ("No likely cause can be established from the available evidence.",)
    assert all(x.startswith("RECOMMENDATION:") for x in advice["recommendations"])
    data = {"contacts": [{"id": "fictional-buyer", "relationship": "buyer"}], "communications": [
        {"id": "fictional-message", "direction": "inbound", "body": "The price is too high", "links": {"property_id": p["id"], "contact_id": "fictional-buyer"}}]}
    advice = advise_property(p, data, inventory_items([p], today=TODAY)[0])
    assert advice["causes"][0].startswith("LIKELY CAUSE:") and "price" in advice["categories"]


def test_corepilot_stale_and_specific_advisor_no_write():
    p = prop(21)
    data = {"properties": [p]}
    before = repr(data)
    result = run_corepilot("Which properties are getting stale?", data)
    assert result.status == "complete"
    result = run_corepilot("Why isn’t this property selling?", data, context={"property_id": p["id"]})
    assert result.inventory_causes and any("Missing" in x for x in result.what_i_found)
    assert result.records_written == result.external_actions_started == 0 and repr(data) == before


def test_negated_buyer_message_is_not_a_price_objection():
    p = prop(21)
    data = {"contacts": [{"id": "b", "relationship": "buyer"}], "communications": [
        {"id": "m", "direction": "inbound", "body": "I do not think the price is too high", "links": {"property_id": p["id"], "contact_id": "b"}}]}
    assert not advise_property(p, data, inventory_items([p], today=TODAY)[0])["categories"]


def test_configurable_threshold_and_invalid_date():
    assert inventory_items([prop(9)], today=TODAY, thresholds=(7, 14, 21))[0]["priority"] == "Needs attention"
    assert inventory_items([prop(listed_at="bad date")], today=TODAY)[0]["days_active"] is None


@pytest.mark.parametrize("query", ["What properties have been for sale more than 10 days?", "Which properties have had no meaningful change in 14 days?",
                                  "What is our oldest active inventory?", "Which properties need a price change?", "Which properties need better terms?"])
def test_inventory_numbers_are_not_mistaken_for_addresses(query):
    result = run_corepilot(query, {"properties": [prop(21)]})
    assert result.status == "complete" and not result.clarification


def test_existing_scheduled_runtime_saves_derived_attention_once(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from cfh_disposition import property_change_runtime as runtime

    p = prop(21)
    monkeypatch.setattr("cfh_disposition.property_change_cache.RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(runtime, "load_baseline_source", lambda secrets, **kwargs: ([source_row()], "fictional"))
    monkeypatch.setattr(runtime, "read_canonical_records", lambda *args: [p])
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace())
    secrets = {"GOOGLE_SHEET_ID": "fictional", "SUPABASE_URL": "fictional", "SUPABASE_SERVICE_ROLE_KEY": "fictional"}
    runtime.read_property_changes(secrets, force=True)
    first = runtime.latest_property_check(secrets)
    assert len(first["stale_inventory"]["attention"]) == 1 and len(first["stale_inventory"]["new_ids"]) == 1
    runtime.read_property_changes(secrets, force=True)
    second = runtime.latest_property_check(secrets)
    assert second["stale_inventory"]["new_ids"] == []
    assert len(second["stale_inventory"]["attention"]) == 1


def test_actual_command_bot_form_inventory_and_advisor(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from cfh_disposition.property_change_detection import detect_property_changes

    p = prop(listed_at=(date.today() - timedelta(days=21)).isoformat())
    data = {"properties": [p]}
    before = repr(data)

    def invoke(name, options):
        assert name == "commandcore-crm-core" and options["body"]["action"] == "list"
        return {"ok": True, "records": data.get(options["body"]["entity"], [])}

    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(functions=SimpleNamespace(invoke=invoke)))
    result = detect_property_changes([source_row()], [p], source_reference="fictional")
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *args: result)
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *args: {"inventory_observations": {p["id"]: {"marketing_status": "yellow"}}})
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.run()
        for query, expected in [
            ("Which properties are getting stale?", "Urgent disposition review"),
            ("Find 101 Example Lane", "Property:"),
            ("Why isn’t this property selling?", "No likely cause can be established"),
            ("What needs my attention today?", "stale properties need review"),
            ("Prepare a price change to 84000", "84000"),
            ("Prepare a marketing refresh", "NOT SENT / NOT SAVED"),
        ]:
            page.text_input(key="corepilot_request").set_value(query)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception
            shown = " ".join(str(x.value) for group in (page.markdown, page.warning, page.info) for x in group)
            assert expected in shown
        assert repr(data) == before
    finally:
        st.cache_resource.clear()
