"""Fictional records exercise the real form, loader, router and session context."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from test_corepilot_orchestrator import _records

from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.property_change_detection import detect_property_changes


def records():
    data = _records()
    data["contacts"][0]["role"] = "seller"
    data["communications"] = [{"id": "fictional-message", "body": "The fictional title review is pending.",
                               "direction": "inbound", "received_at": "2026-01-02T12:00:00Z",
                               "links": {"deal_id": "deal-fictional", "contact_id": "contact-fictional"}}]
    data["offers"] = [{"id": "fictional-offer", "status": "draft_pending_owner_approval", "links": {"deal_id": "deal-fictional"}}]
    return data


def test_unknown_address_does_not_reuse_prior_context():
    result = run_corepilot("Find 999 Unknown Street", records(), context={"deal_id": "deal-fictional"})
    assert result.status == "needs_context" and not result.context


def test_property_without_deal_retains_context_without_inventing_closing():
    data = records()
    data["deals"] = []
    first = run_corepilot("Find 101 Example Lane", data)
    second = run_corepilot("What is holding it up?", data, context=dict(first.context))
    assert dict(second.context)["property_id"] == "property-fictional"
    assert "closing progress cannot be verified" in second.needs_attention[0]


def test_named_worker_does_not_match_substring_and_unknown_is_empty():
    data = records()
    for name in ("Gabe", "Sab"):
        result = run_corepilot(f"What does {name} need to handle?", data)
        assert result.what_i_found == ("No open assigned work was found.",)


def test_ambiguous_lookup_and_title_sender_are_not_guessed():
    data = records()
    data["properties"].append({"id": "fictional-other", "address": "101 Example Lane"})
    assert run_corepilot("Find 101 Example Lane", data).status == "needs_context"
    result = run_corepilot("What did the title company say?", data, context={"deal_id": "deal-fictional"})
    assert result.what_i_found == ("No matching recorded conversation was found.",)


def test_draft_is_private_and_stuck_deals_use_recorded_blockers():
    data = records()
    before = repr(data)
    draft = run_corepilot("Draft a follow-up", data, context={"deal_id": "deal-fictional"})
    assert draft.status == "prepared" and draft.records_written == 0
    stuck = run_corepilot("Which deals are stuck?", data)
    assert "Owner approval" in stuck.what_i_found[0]
    assert repr(data) == before


@pytest.mark.parametrize("query", ["Send a response", "Apply property changes", "Delete this deal", "Approve the offer", "Update the price", "Pay the seller"])
def test_actions_always_blocked(query):
    data = records()
    before = repr(data)
    result = run_corepilot(query, data, context={"deal_id": "deal-fictional"})
    assert result.status == "approval_required"
    assert result.records_written == result.external_actions_started == 0 and before == repr(data)


def test_real_page_multi_turn_routes(monkeypatch):
    data = records()
    before = json.dumps(data, sort_keys=True)
    calls = []

    def invoke(name, options):
        assert name == "commandcore-crm-core"
        body = options["body"]
        assert body["action"] == "list"
        calls.append(body)
        return {"ok": True, "records": data.get(body["entity"], [])}

    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(functions=SimpleNamespace(invoke=invoke)))
    unchanged = detect_property_changes([], [], source_reference="fictional")
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *args: unchanged)
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *args: {})
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update({"APP_PASSWORD": "fictional-password", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional-key"})
        page.session_state.authenticated = True
        page.run()
        cases = [
            ("Find 101 Example Lane", "Deal: Example Lane deal"),
            ("What is holding it up?", "Owner approval"),
            ("Show me the last conversation with this seller", "fictional title review"),
            ("What work does Sabrina have?", "Confirm fictional title update"),
            ("What approvals are waiting on me?", "Offer recommendation"),
            ("Show me properties that changed", "No matching property changes"),
            ("What changed on it?", "No matching property changes"),
            ("Find Example Lane deal", "Deal: Example Lane deal"),
            ("What happened last?", "Communication received"),
            ("Send a response", "actions are disabled"),
            ("purple elephant", "What would you like CorePilot"),
        ]
        for question, expected in cases:
            page.text_input(key="corepilot_request").set_value(question)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception
            shown = " ".join(str(item.value) for group in (page.markdown, page.info, page.warning) for item in group)
            assert expected in shown, (question, shown)
        assert json.dumps(data, sort_keys=True) == before
        assert len(calls) == 9 * len(cases)
    finally:
        st.cache_resource.clear()


@pytest.mark.parametrize("payload", [{"ok": False, "records": []}, {"ok": True}, {"records": "invalid"}])
def test_real_page_failed_reads_never_claim_all_clear(monkeypatch, payload):
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(functions=SimpleNamespace(invoke=lambda *args: payload)))
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update({"APP_PASSWORD": "fictional-password", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional-key"})
        page.session_state.authenticated = True
        page.run()
        page.text_input(key="corepilot_request").set_value("Show my work")
        page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
        assert not page.exception
        assert any("complete answer cannot be verified" in item.value for item in page.warning)
        assert not any("No open assigned work" in item.value for item in page.markdown)
    finally:
        st.cache_resource.clear()
