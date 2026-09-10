import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_corepilot_conversation import records

from cfh_disposition.corepilot_orchestrator import run_corepilot


def private_test_storage():
    saved = {}

    def upload(path, payload, file_options):
        assert file_options["upsert"] == "false" and path.split("/")[0] in {"tasks", "activities", "communications"}
        if path in saved:
            raise RuntimeError("Duplicate")
        saved[path] = payload

    return SimpleNamespace(from_=lambda name: SimpleNamespace(upload=upload, download=lambda path: saved[path]))


def fixture_records():
    data = records()
    data["contacts"][0].update(relationship="seller", sms_consent=True, assigned_to="Fictional owner")
    data["deals"][0]["assigned_to"] = "Fictional owner"
    data["communications"][0].update(body="Checking in for an update", channel="sms")
    return data


@pytest.mark.parametrize("question,kind", [
    ("Draft a reply.", "Communication draft"),
    ("Write a follow-up text for this lead.", "Communication draft"),
    ("What should I say back?", "Communication draft"),
    ("Have Sabrina follow up tomorrow.", "Proposed task"),
    ("Prepare a task for Gabe to check this deal.", "Proposed task"),
    ("Prepare a task for Jordan to call tomorrow.", "Proposed task"),
    ("Prepare the next step.", "Proposed next action"),
    ("Give me the next action for this deal.", "Proposed next action"),
    ("Prepare owner approval.", "Owner-approval preparation"),
])
def test_structured_previews_are_pure(question, kind):
    data = fixture_records()
    before = json.dumps(data, sort_keys=True)
    selected = run_corepilot("Find 101 Example Lane", data)
    result = run_corepilot(question, data, context=dict(selected.context))
    assert result.status == "prepared" and result.prepared_action.what == kind
    assert result.prepared_action.status == "NOT SENT / NOT SAVED"
    assert result.records_written == result.external_actions_started == 0
    assert json.dumps(data, sort_keys=True) == before
    if "tomorrow" in question:
        assert result.prepared_action.due_timing == "tomorrow"
    if kind == "Communication draft":
        assert "Could you" in result.prepared_action.proposal


@pytest.mark.parametrize("mutation", ["stop", "no_consent", "suppressed", "legal", "money", "ambiguous"])
def test_existing_communications_controls_withhold_unsafe_drafts(mutation):
    data = fixture_records()
    if mutation == "stop":
        data["communications"][0]["body"] = "STOP"
    elif mutation == "no_consent":
        data["contacts"][0]["sms_consent"] = False
    elif mutation == "suppressed":
        data["contacts"][0]["suppressed"] = True
    elif mutation == "legal":
        data["communications"][0]["body"] = "Change the contract legal terms"
    elif mutation == "money":
        data["communications"][0]["body"] = "Wire the money"
    else:
        data["communications"].append({**data["communications"][0], "id": "fictional-second"})
    result = run_corepilot("Draft a reply", data, context={"deal_id": "deal-fictional"})
    assert result.status == "needs_context" if mutation == "ambiguous" else "Draft withheld" in result.prepared_action.proposal
    assert result.records_written == result.external_actions_started == 0


def test_ambiguous_preparation_and_unknown_property_do_not_guess():
    data = fixture_records()
    assert run_corepilot("Prepare something", data, context={"deal_id": "deal-fictional"}).status == "needs_context"
    assert run_corepilot("Draft a reply", data).status == "needs_context"
    assert run_corepilot("Prepare a task", data, context={"deal_id": "deal-fictional"}).status == "needs_context"


def test_older_selected_message_cannot_bypass_stop_or_cross_deal_context():
    data = fixture_records()
    data["communications"].append({**data["communications"][0], "id": "fictional-stop", "body": "STOP"})
    ctx = {"deal_id": "deal-fictional", "communication_id": "fictional-message"}
    result = run_corepilot("Draft a reply", data, context=ctx)
    assert "Draft withheld" in result.prepared_action.proposal
    data["communications"][0]["links"]["deal_id"] = "different-deal"
    assert run_corepilot("Draft a reply", data, context=ctx).status == "needs_context"


def test_property_update_reuses_existing_patch_validation():
    from test_property_sync_preview import property_record, source_row

    from cfh_disposition.property_change_detection import detect_property_changes

    prop = property_record()
    changes = detect_property_changes([source_row(monthly_payment="895")], [prop], source_reference="fictional")
    data = {"properties": [prop]}
    result = run_corepilot("Prepare an update for this property", data, context={"property_id": prop["id"]}, property_changes=changes)
    assert "monthly_payment" in result.prepared_action.proposal and "895" in result.prepared_action.proposal
    assert prop["monthly_payment"] == "900"


def test_real_streamlit_preparation_session(monkeypatch):
    data = fixture_records()
    before = json.dumps(data, sort_keys=True)
    calls = []

    def invoke(name, options):
        assert name == "commandcore-crm-core"
        payload = options["body"]
        assert payload["action"] == "list"
        calls.append(payload)
        return {"ok": True, "records": data.get(payload["entity"], [])}

    storage = private_test_storage()
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(functions=SimpleNamespace(invoke=invoke), storage=storage))
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update({"APP_PASSWORD": "fictional-password", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional-key"})
        page.session_state.authenticated = True
        page.run()
        for query, expected in [
            ("Find 101 Example Lane", "Deal: Example Lane deal"),
            ("Draft a reply.", "Could you please"),
            ("Show me the last conversation with this seller", "Checking in"),
            ("What should I say back?", "NOT SENT / NOT SAVED"),
            ("Have Sabrina follow up tomorrow.", "Proposed assignee:"),
            ("Prepare the next step.", "Prepared action"),
            ("Prepare something", "Do you want a communication draft"),
        ]:
            page.text_input(key="corepilot_request").set_value(query)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception
            shown = " ".join(str(x.value) for group in (page.markdown, page.info, page.warning) for x in group)
            assert expected in shown, shown
            assert page.session_state.corepilot_context["property_id"] == "property-fictional"
        assert len(calls) == 63 and json.dumps(data, sort_keys=True) == before
        assert page.session_state.corepilot_context["communication_id"] == "fictional-message"
    finally:
        st.cache_resource.clear()


@pytest.mark.parametrize("interruption", ["none", "source_failure", "blocked_send"])
def test_property_task_then_reply_preserves_real_page_context(monkeypatch, interruption):
    # Same live sequence, with a fictional address for public repository safety.
    # Property-only canonical baseline: no invented linked seller or deal.
    data = {"properties": [{"id": "fictional-property", "address": "101 Example Lane"}]}
    failing = False

    def invoke(name, options):
        assert name == "commandcore-crm-core"
        body = options["body"]
        assert body == {"action": "list", "entity": body["entity"], "limit": 500}
        if failing and body["entity"] == "properties":
            raise RuntimeError("Fictional temporary read failure")
        return {"ok": True, "records": data.get(body["entity"], [])}

    storage = private_test_storage()
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(functions=SimpleNamespace(invoke=invoke), storage=storage))
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update({"APP_PASSWORD": "fictional-password", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional-key"})
        page.session_state.authenticated = True
        page.run()

        def ask(query):
            page.text_input(key="corepilot_request").set_value(query)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception

        ask("Find 101 Example Lane.")
        ask("Have Sabrina follow up tomorrow.")
        assert any("SAVED INTERNALLY / NOT SENT" in x.value for x in page.info)
        assert page.session_state.corepilot_context == {"property_id": "fictional-property"}
        if interruption == "source_failure":
            failing = True
            ask("Draft a reply.")
            assert any("complete answer cannot be verified" in x.value for x in page.warning)
            assert page.session_state.corepilot_context == {"property_id": "fictional-property"}
            failing = False
        elif interruption == "blocked_send":
            ask("Send a reply.")
            assert page.session_state.corepilot_context == {"property_id": "fictional-property"}
        ask("Draft a reply.")
        assert any("Still working with 101 Example Lane" in x.value and "message and recipient" in x.value for x in page.info)
        assert not any("Which property, deal" in x.value for x in page.info)
        assert page.session_state.corepilot_context == {"property_id": "fictional-property"}
        ask("Draft a reply.")
        assert page.session_state.corepilot_context == {"property_id": "fictional-property"}
    finally:
        st.cache_resource.clear()
