import copy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from cfh_disposition.corepilot_work import manage_work, update_internal_record


@pytest.fixture
def crm(monkeypatch):
    data = {"properties": [{"id": "p", "address": "101 Example Lane"}],
            "tasks": [{"id": "t", "title": "Follow up on 101 Example Lane", "assigned_to": "Sabrina", "status": "open",
                       "internal_only": True, "due_date": "2026-09-10", "links": {"property_id": "p"}}],
            "contacts": [{"id": "worker-context", "assigned_to": "Gabe"}],
            "communications": [{"id": "draft", "status": "draft", "direction": "outbound_draft", "internal_only": True,
                                "body": "Fictional original reply", "links": {"property_id": "p"}, "send_enabled": False}]}
    calls = []

    def invoke(name, options):
        assert name == "commandcore-crm-core"
        body = options["body"]
        entity = body["entity"]
        if body["action"] == "list":
            return {"ok": True, "records": copy.deepcopy(data.get(entity, []))}
        assert entity in {"tasks", "communications"}
        if body["action"] == "get":
            return {"ok": True, "record": copy.deepcopy(next(r for r in data[entity] if r["id"] == body["id"]))}
        assert body["action"] == "upsert"
        calls.append(copy.deepcopy(body))
        row = next(r for r in data[entity] if r["id"] == body["record"]["id"])
        row.update(body["record"])
        return {"ok": True, "record": copy.deepcopy(row)}

    client = SimpleNamespace(functions=SimpleNamespace(invoke=invoke))
    monkeypatch.setattr("supabase.create_client", lambda *args: client)
    return data, calls, client


def test_real_streamlit_task_sequence_and_private_draft(crm):
    data, calls, _ = crm
    protected = copy.deepcopy(data["properties"])
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.run()

        def ask(q):
            page.text_input(key="corepilot_request").set_value(q)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception

        ask("What work does Sabrina have?")
        assert page.session_state.corepilot_context["task_id"] == "t"
        ask("Move that to Friday.")
        assert date.fromisoformat(data["tasks"][0]["due_date"]).weekday() == 4
        ask("Give it to Gabe.")
        assert data["tasks"][0]["assigned_to"] == "Gabe"
        ask("Add a note that we are waiting on the seller.")
        assert data["tasks"][0]["internal_notes"][0]["text"] == "we are waiting on the seller"
        ask("Mark it done.")
        assert data["tasks"][0]["status"] == "done"
        count = len(calls)
        ask("Mark it done.")
        assert len(calls) == count
        assert len(data["tasks"][0]["internal_history"]) == 4
        assert page.session_state.corepilot_context["task_id"] == "t"
        ask("Show the private draft")
        ask("Revise that draft with Thank you for the update")
        assert data["communications"][0]["body"] == "Thank you for the update"
        assert data["communications"][0]["internal_history"][0]["changes"]["body"]["old"] == "Fictional original reply"
        count = len(calls)
        ask("Send that draft")
        assert len(calls) == count
        assert data["communications"][0]["status"] == "draft" and data["communications"][0]["send_enabled"] is False
        assert data["properties"] == protected
    finally:
        st.cache_resource.clear()


def test_ambiguity_clears_prior_task_and_requires_selection(crm):
    data, calls, _ = crm
    data["tasks"].append({**data["tasks"][0], "id": "t2", "title": "Other task"})
    result = manage_work("What work does Sabrina have?", data, {"task_id": "t"}, None)
    assert result.clarification and "task_id" not in dict(result.context)
    result = manage_work("Mark it done", data, dict(result.context), None)
    assert result.clarification and not calls


def test_unknown_assignee_and_cross_context_cannot_write(crm):
    data, calls, client = crm
    def writer(e, r, p, a):
        return update_internal_record(client, e, r, p, a)
    assert manage_work("Give it to Unknown Person", data, {"task_id": "t"}, writer).clarification
    assert manage_work("Mark it done", data, {"task_id": "t", "property_id": "other"}, writer).clarification
    assert not calls


def test_stale_read_stops_and_business_fields_are_blocked(crm):
    data, calls, client = crm
    old = copy.deepcopy(data["tasks"][0])
    data["tasks"][0]["assigned_to"] = "Gabe"
    with pytest.raises(ValueError):
        update_internal_record(client, "tasks", old, {"status": "done"}, "Owner")
    with pytest.raises(PermissionError):
        update_internal_record(client, "tasks", old, {"price": 1}, "Owner")
    with pytest.raises(PermissionError):
        update_internal_record(client, "properties", old, {"status": "done"}, "Owner")
    assert not calls


def test_real_page_updater_wiring_and_legacy_runtime_guard(crm, monkeypatch):
    from cfh_disposition import corepilot_internal

    data, calls, _ = crm
    before = copy.deepcopy(data)
    current = corepilot_internal.run_internal_command
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.run()

        def ask(query):
            page.text_input(key="corepilot_request").set_value(query)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception

        def legacy(request, records, *, writer, **kwargs):
            raise AssertionError("The old wrapper must not receive updater through kwargs")

        monkeypatch.setattr(corepilot_internal, "run_internal_command", legacy)
        ask("What work does Sabrina have?")
        assert any("Restart CommandCore" in x.value for x in page.warning)
        assert data == before and not calls
        monkeypatch.setattr(corepilot_internal, "run_internal_command", current)
        ask("Find 101 Example Lane")  # Falls through to the read-only orchestrator, without updater.
        ask("What work does Sabrina have?")
        assert page.session_state.corepilot_context["task_id"] == "t"
        assert data == before and not calls
        ask("Move that to Friday.")  # Only this isolated fixture is changed.
        assert len(calls) == 1 and calls[0]["entity"] == "tasks"
        assert "due_date" in calls[0]["record"]
    finally:
        st.cache_resource.clear()
