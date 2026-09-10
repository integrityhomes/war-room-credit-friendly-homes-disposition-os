import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_property_sync_preview import property_record, source_row

from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.property_change_attention import LOCKBOX, MARKETING, change_lines, public_evidence
from cfh_disposition.property_change_cache import decode_result, encode_result
from cfh_disposition.property_change_detection import RETURNED, SOLD_CHANGE, detect_property_changes


def check(row, prop, previous=None):
    return detect_property_changes([row], [prop], source_reference="fictional", previous=previous, lockbox_key="fictional-private-test-key")


@pytest.mark.parametrize("field,value", [("asking_or_sale_price", "85000"), ("monthly_payment", "875"), ("down_payment", "2500"), ("interest_rate", "10")])
def test_financial_changes_have_values_and_no_repeat_events(field, value):
    prop = property_record(down_payment="3000", interest_rate="12")
    row = source_row(down_payment="3000", interest_rate="12")
    initial = check(row, prop)
    changed = replace(row, fields={**row.fields, field: value})
    result = check(changed, prop, initial.state)
    assert len(result.observed_new_events) == 1
    assert any(c.field == field and Decimal(c.proposed) == Decimal(value) for c in result.observed_changes[0].evidence.changes)
    repeated = check(changed, prop, result.state)
    assert not repeated.observed_new_events
    assert repeated.observed_changes[0].event_id == result.observed_changes[0].event_id
    reverted = check(row, prop, repeated.state)
    assert reverted.observed_new_events
    again = check(changed, prop, reverted.state)
    assert again.observed_new_events[0].event_id != result.observed_new_events[0].event_id


def test_lockbox_never_exposes_codes_in_evidence_checkpoint_or_alert():
    old, new = "fictional-code-old", "fictional-code-new"
    general = public_evidence({"lockbox_code": new, "notes": "Access note " + new})
    assert new not in json.dumps(general)
    prop = property_record(lockbox_code=old)
    row = source_row(lockbox_code=old)
    first = check(row, prop)
    assert not any(LOCKBOX in e.categories for e in first.observed_changes)
    row = replace(row, fields={**row.fields, "lockbox_code": new, "notes": "Access note " + new})
    changed = check(row, prop, first.state)
    assert any(LOCKBOX in e.categories and e.priority == "High" for e in changed.observed_new_events)
    serialized = json.dumps(encode_result(changed))
    assert old not in serialized and new not in serialized
    assert "Lockbox code changed." in " ".join(change_lines(changed, "Did any lockbox codes change?"))
    repeated = check(row, prop, decode_result(encode_result(changed)).state)
    assert not repeated.observed_new_events
    removed = check(replace(row, fields={**row.fields, "lockbox_code": None}, lockbox_observed=True), prop, repeated.state)
    assert any(LOCKBOX in e.categories for e in removed.observed_new_events)


def test_marketing_and_sold_transitions():
    prop = property_record()
    white = replace(source_row(), marketing_status="white")
    first = check(white, prop)
    yellow = replace(white, marketing_status="yellow")
    marketed = check(yellow, prop, first.state)
    assert MARKETING in marketed.observed_new_events[0].categories
    stopped = check(white, prop, marketed.state)
    assert MARKETING in stopped.observed_new_events[0].categories
    sold = replace(yellow, fields={**yellow.fields, "availability": "Sold / Unavailable"})
    unavailable = check(sold, prop, stopped.state)
    assert SOLD_CHANGE in unavailable.observed_new_events[0].categories and unavailable.observed_new_events[0].priority == "High"
    returned = check(yellow, prop, unavailable.state)
    assert RETURNED in returned.observed_new_events[0].categories


def test_attention_combines_critical_changes_and_stale_inventory():
    prop = property_record()
    row = source_row()
    before = check(row, prop)
    result = check(replace(row, fields={**row.fields, "monthly_payment": "875"}), prop, before.state)
    obs = {prop["id"]: {"status": "available", "marketing_status": "yellow",
                        "marketing_observed_since": (datetime.now(UTC).date() - timedelta(days=21)).isoformat()}}
    answer = run_corepilot("What needs my attention?", {"properties": [prop]}, property_changes=result, inventory_evidence=obs)
    assert "monthly payment" in " ".join(answer.what_i_found) and "Urgent disposition review" in " ".join(answer.what_i_found)
    assert answer.records_written == answer.external_actions_started == 0


def test_real_streamlit_multiple_changes_and_lockbox_redaction(monkeypatch):
    props = [property_record(lockbox_code="fictional-private-old"), property_record(id="second", address="202 Example Lane")]
    rows = [source_row(lockbox_code="fictional-private-old"), source_row(id="second", address="202 Example Lane")]
    first = detect_property_changes(rows, props, source_reference="fictional", lockbox_key="fictional-key")
    changed = [replace(rows[0], fields={**rows[0].fields, "lockbox_code": "fictional-private-new"}),
               replace(rows[1], fields={**rows[1].fields, "monthly_payment": "875"})]
    result = detect_property_changes(changed, props, source_reference="fictional", previous=first.state, lockbox_key="fictional-key")
    assert len(result.observed_new_events) == 2
    def invoke(name, options):
        assert name == "commandcore-crm-core" and options["body"]["action"] == "list"
        return {"ok": True, "records": props if options["body"]["entity"] == "properties" else []}
    monkeypatch.setattr("supabase.create_client", lambda *a: SimpleNamespace(functions=SimpleNamespace(invoke=invoke)))
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *a: result)
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *a: {})
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.run()
        for query in ("Show me all important property changes.", "What needs my attention?", "Did any lockbox codes change?"):
            page.text_input(key="corepilot_request").set_value(query)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception
            shown = " ".join(str(x.value) for group in (page.markdown, page.info, page.warning, page.caption) for x in group)
            assert "Lockbox code changed." in shown
            assert "fictional-private-old" not in shown and "fictional-private-new" not in shown
            if "lockbox" not in query:
                assert "202 Example Lane" in shown and "$875.00" in shown
    finally:
        st.cache_resource.clear()
