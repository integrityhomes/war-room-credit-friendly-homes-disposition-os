import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_corepilot_preparation import fixture_records

from cfh_disposition.corepilot_internal import create_internal_record, run_internal_command


@pytest.fixture
def runtime(monkeypatch):
    data = fixture_records()
    saved = {}
    writes = []

    class Bucket:
        def upload(self, path, payload, file_options):
            assert file_options["upsert"] == "false"
            assert path.split("/")[0] in {"tasks", "communications", "activities"}
            if path in saved:
                raise RuntimeError("Duplicate")
            saved[path] = payload
            record = json.loads(payload)
            data.setdefault(record["entity_type"], []).append(record)
            writes.append(record)

        def download(self, path):
            return saved[path]

    def invoke(name, options):
        assert name == "commandcore-crm-core" and options["body"]["action"] == "list"
        return {"ok": True, "records": data.get(options["body"]["entity"], [])}

    bucket = Bucket()
    client = SimpleNamespace(functions=SimpleNamespace(invoke=invoke), storage=SimpleNamespace(from_=lambda name: bucket))
    monkeypatch.setattr("supabase.create_client", lambda *args: client)
    return data, writes, client


def test_real_streamlit_internal_actions_context_and_duplicates(runtime):
    data, writes, _ = runtime
    business_before = json.dumps({k: data[k] for k in ("properties", "deals", "contacts")}, sort_keys=True)
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.session_state.commandcore_worker_name = "Fictional owner"
        page.run()

        def ask(q):
            page.text_input(key="corepilot_request").set_value(q)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception
            return " ".join(str(x.value) for group in (page.markdown, page.info, page.warning, page.success) for x in group)

        ask("Find 101 Example Lane")
        assert "Task created" in ask("Have Sabrina follow up tomorrow.")
        assert writes[-1]["assigned_to"] == "Sabrina"
        links = dict(writes[-1]["links"])
        assert "duplicate prevented" in ask("Have Sabrina follow up tomorrow.")
        assert len(writes) == 1
        assert "DRAFT SAVED" in ask("Draft a reply.")
        assert writes[-1]["direction"] == "outbound_draft" and writes[-1]["status"] == "draft"
        assert "duplicate prevented" in ask("Save that reply as a draft.")
        assert len(writes) == 2
        assert "Task created" in ask("Make me a task to review this tomorrow.")
        assert writes[-1]["assigned_to"] == "Fictional owner" and writes[-1]["links"] == links
        assert "Task created" in ask("Give Gabe a task to check this property Friday.")
        assert date.fromisoformat(writes[-1]["due_date"]).weekday() == 4
        assert "Next action saved" in ask("Prepare the next action for this deal.")
        count = len(writes)
        for q in ("Send the reply", "Apply the price change", "Close this deal", "Approve payment"):
            ask(q)
        assert len(writes) == count
        data["properties"].append({"id": "second-fictional", "address": "202 Imaginary Road"})
        ask("Find 202 Imaginary Road")
        assert "Which reply" in ask("Save that reply as a draft.")
        assert "recipient" in ask("Draft a reply.")
        assert len(writes) == count
        data["properties"].pop()
        assert business_before == json.dumps({k: data[k] for k in ("properties", "deals", "contacts")}, sort_keys=True)
        assert all(r["internal_only"] and not r["external_action_started"] for r in writes)
    finally:
        st.cache_resource.clear()


def test_storage_conflict_reuses_record_without_overwrite(runtime):
    data, writes, client = runtime
    snapshot = json.loads(json.dumps(data))
    def writer(entity, record):
        return create_internal_record(client, entity, record)
    args = {"writer": writer, "context": {"deal_id": "deal-fictional"}, "today": date(2026, 9, 9)}
    first = run_internal_command("Have Jordan follow up tomorrow", snapshot, **args)
    second = run_internal_command("Have Jordan follow up tomorrow", snapshot, **args)
    assert first.records_written == 1 and second.records_written == 0 and len(writes) == 1
    assert writes[0]["due_date"] == "2026-09-10"


@pytest.mark.parametrize("query", ["Make me a task to review this tomorrow", "Have Jordan review this", "Have Jordan check and delete this tomorrow"])
def test_missing_or_unsafe_task_details_do_not_write(query, runtime):
    data, writes, client = runtime
    result = run_internal_command(query, data, context={"deal_id": "deal-fictional"}, writer=lambda e, r: create_internal_record(client, e, r))
    assert result.clarification and not writes


def test_consent_stop_prevents_draft_save(runtime):
    data, writes, client = runtime
    data["communications"][0]["body"] = "STOP"
    result = run_internal_command("Draft a reply", data, context={"deal_id": "deal-fictional"}, writer=lambda e, r: create_internal_record(client, e, r))
    assert "Draft withheld" in result.prepared_action.proposal and not writes


def test_writer_rejects_business_updates(runtime):
    _, _, client = runtime
    with pytest.raises(PermissionError):
        create_internal_record(client, "properties", {"source": "corepilot-internal", "internal_only": True})


def test_new_session_does_not_inherit_selected_property(runtime):
    data, writes, client = runtime
    result = run_internal_command("Have Jordan follow up tomorrow", data, writer=lambda e, r: create_internal_record(client, e, r))
    assert result.clarification and not writes


def test_uncertain_save_never_claims_success(runtime):
    data, writes, _ = runtime

    def unavailable(entity, record):
        raise RuntimeError("Private provider failure")

    result = run_internal_command("Have Jordan follow up tomorrow", data, context={"deal_id": "deal-fictional"}, writer=unavailable)
    assert result.status == "safe_failure" and result.records_written == 0 and not writes
    assert "Private provider" not in str(result)


def test_private_draft_not_treated_as_inbound_attention(runtime):
    from cfh_disposition.commandcore_nevaeh_inbox import build_nevaeh_inbox

    data, writes, client = runtime
    run_internal_command("Draft a reply", data, context={"deal_id": "deal-fictional"}, writer=lambda e, r: create_internal_record(client, e, r))
    items = build_nevaeh_inbox(data["communications"], contacts=data["contacts"], properties=data["properties"], deals=data["deals"])
    assert writes and writes[0]["id"] not in {i.communication_id for i in items}


def test_streamlit_stale_enum_stops_before_save_then_retry_is_idempotent(runtime, monkeypatch):
    from cfh_disposition import corepilot_tools

    _, writes, _ = runtime
    current = corepilot_tools.CorePilotActionClass
    legacy = SimpleNamespace(READ=current.READ, PREPARE=current.PREPARE, APPROVAL_REQUIRED=current.APPROVAL_REQUIRED)
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.run()

        def ask():
            # Same explicit-address grammar as the live report; fictional public fixture.
            page.text_input(key="corepilot_request").set_value("Have Sabrina follow up on 101 Example Lane tomorrow.")
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception

        monkeypatch.setattr(corepilot_tools, "CorePilotActionClass", legacy)
        ask()
        assert not writes and any("restart" in item.value for item in page.warning)
        monkeypatch.setattr(corepilot_tools, "CorePilotActionClass", current)
        ask()
        assert len(writes) == 1 and writes[0]["assigned_to"] == "Sabrina"
        assert writes[0]["links"]["property_id"] == "property-fictional"
        ask()
        assert len(writes) == 1 and any("duplicate prevented" in item.value for item in page.markdown)
    finally:
        st.cache_resource.clear()
