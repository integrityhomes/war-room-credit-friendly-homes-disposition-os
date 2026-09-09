import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import supabase

ROOT = Path(__file__).resolve().parents[1]


def test_corepilot_page_is_simple_and_read_only() -> None:
    source = (ROOT / "pages" / "49_CommandCore_Command_Bot.py").read_text(encoding="utf-8")
    assert 'render_page_header("CorePilot"' in source
    assert "What do you need?" in source
    assert "What I found" in source
    assert "Needs attention" in source
    assert "Recommended next step" in source
    assert "Advanced settings" not in source  # shared collapsed UX helper supplies the label
    assert '"action": "list"' in source
    assert '"action": "upsert"' not in source
    assert '"action": "create"' not in source
    assert "dispatch_command" not in source
    assert 'st.form_submit_button("Ask CorePilot"' in source
    assert "except Exception as exc" in source
    assert "couldn't check one part of CommandCore right now" in source


def test_navigation_uses_official_user_facing_name() -> None:
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"Ask CorePilot"' in app
    assert 'title="CorePilot"' in app


@pytest.mark.parametrize("question", [
    "101 Example Lane, Example City, IL 60000",
    "What is holding up the closing on 101 Example Lane, Example City, IL 60000?",
    "For 101 Example Lane, Example City, IL 60000, what is the next step?",
])
@pytest.mark.parametrize("response_format", ["bytes", "bytearray", "dict", "data"])
def test_corepilot_submission_decodes_crm_response_and_resolves_deal(monkeypatch, question, response_format) -> None:
    # Only replace the external transport. Execute the actual page, form, loader,
    # response decoder, canonical links, orchestrator, and result rendering.
    records = {
        "properties": [{"id": "fictional-property", "name": "Fictional home", "address": "101 Example Lane", "city": "Example City", "state": "IL", "zip": "60000"}],
        "deals": [{"id": "fictional-deal", "title": "Fictional closing", "stage": "closing", "links": {"property_id": "fictional-property"}}],
        "tasks": [{"id": "fictional-task", "title": "Check fictional title", "status": "blocked", "blocked_reason": "Fictional title delay", "links": {"deal_id": "fictional-deal"}}],
    }
    before = json.dumps(records, sort_keys=True)
    calls = []

    def invoke(name, options):
        assert name == "commandcore-crm-core"
        payload = options["body"]
        assert payload == {"action": "list", "entity": payload["entity"], "limit": 500}
        calls.append(payload["entity"])
        rows = records.get(payload["entity"], [])
        response = {"ok": True, "entity": payload["entity"], "records": rows, "count": len(rows)}
        encoded = json.dumps(response).encode("utf-8")
        return {"bytes": encoded, "bytearray": bytearray(encoded), "dict": response, "data": SimpleNamespace(data=encoded)}[response_format]

    def create_client(url, key, options):
        assert options.function_client_timeout == 60
        return SimpleNamespace(functions=SimpleNamespace(invoke=invoke))

    monkeypatch.setattr(supabase, "create_client", create_client)
    st.cache_resource.clear()
    try:
        app = AppTest.from_file(str(ROOT / "pages" / "49_CommandCore_Command_Bot.py"))
        app.secrets.update({"APP_PASSWORD": "fictional-test-password", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional-test-key"})
        app.session_state["authenticated"] = True
        app.run()
        app.text_input(key="corepilot_request").set_value(question)
        app.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
        assert not app.exception
        assert len(calls) == 9
        assert "properties" in calls and "deals" in calls
        assert any("Deal: Fictional closing" in item.value for item in app.markdown)
        assert any("Fictional title delay" in item.value for item in app.warning)
        assert not any("Which deal" in item.value for item in app.info)
        assert any("Records changed: 0" in item.value for item in app.markdown)
        assert any("External actions started: 0" in item.value for item in app.markdown)
        assert json.dumps(records, sort_keys=True) == before
    finally:
        st.cache_resource.clear()
