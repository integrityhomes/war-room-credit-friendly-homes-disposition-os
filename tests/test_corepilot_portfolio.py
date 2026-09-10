import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from cfh_disposition.corepilot_inventory import inventory_items, stale_checkpoint
from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.corepilot_portfolio import financial_options, portfolio, portfolio_answer
from cfh_disposition.property_change_detection import detect_property_changes


def fixture():
    today = datetime.now(UTC).date()
    props, observations = [], {}
    for key, age, color, status in (("nine", 9, "yellow", "available"), ("ten", 10, "yellow", "available"),
                                   ("fourteen", 14, "yellow", "available"), ("urgent", 21, "yellow", "available"),
                                   ("white", 90, "white", "available"), ("sold", 90, "yellow", "soldunavailable")):
        props.append({"id": key, "address": key + " Fictional Lane", "asking_or_sale_price": "90000", "down_payment": "3000"})
        observations[key] = {"status": status, "marketing_status": color, "marketing_observed_since": (today - timedelta(days=age)).isoformat()}
    return {"properties": props, "tasks": [], "contacts": [], "communications": [], "activities": []}, observations


@pytest.mark.parametrize("query", ["What properties need help selling?", "Show me all stale inventory.", "What has been marketed more than 10 days?",
                                  "What are my worst properties right now?", "Which properties should we work on first?", "Which property should we fix first?",
                                  "Which properties are hardest to sell?", "What should we do to get these sold?", "Give me a plan for every stale property.",
                                  "Which ones need better marketing?", "What property should we attack first?"])
def test_portfolio_questions_need_no_address(query):
    data, observations = fixture()
    before = copy.deepcopy(data)
    answer = run_corepilot(query, data, inventory_evidence=observations)
    found = " ".join(answer.what_i_found)
    assert "urgent Fictional Lane" in found and "fourteen Fictional Lane" in found
    assert ("ten Fictional Lane" in found) == ("more than 10" not in query)
    assert not any(x in found for x in ("white Fictional", "sold Fictional", "nine Fictional"))
    assert "PROPOSED PLAN" in answer.recommended_next_step and "72 hours" in answer.recommended_next_step
    assert data == before and answer.records_written == answer.external_actions_started == 0


def test_thresholds_ranking_and_stable_attention_item():
    data, obs = fixture()
    plans = portfolio(data, obs)
    assert [p["property_id"] for p in plans] == ["urgent", "fourteen", "ten"]
    first = stale_checkpoint(data["properties"], obs)
    second = stale_checkpoint(data["properties"], obs, first)
    assert len(second["attention"]) == 3 and not second["new_ids"]
    later = inventory_items(data["properties"], obs, today=datetime.now(UTC).date() + timedelta(days=4))
    ten = next(i for i in first["attention"] if i["property_id"] == "ten")
    raised = next(i for i in later if i["property_id"] == "ten")
    assert raised["priority"] == "Higher priority" and raised["attention_item_id"] == ten["attention_item_id"]


def test_missing_evidence_and_early_on_demand_still_have_practical_plan():
    data, obs = fixture()
    answer = run_corepilot("What would make this sell?", data, context={"property_id": "nine"}, inventory_evidence=obs)
    assert "Review existing buyer inquiries" in answer.recommended_next_step
    assert "72 hours" in answer.recommended_next_step and answer.needs_attention
    complete = portfolio_answer("all stale", {"properties": data["properties"]}, obs)
    assert "unavailable" in " ".join(complete.evidence) and "PROPOSED PLAN" in complete.recommended_next_step


def test_numbers_require_recorded_inputs_without_market_guess():
    assert not financial_options({"asking_or_sale_price": "N/A"})
    assert "implied principal $87,000.00" in financial_options({"asking_or_sale_price": 90000, "down_payment": 3000})[0]
    options = financial_options({"asking_or_sale_price": 90000, "down_payment": 3000, "interest_rate": 0, "amortization_months": 100})
    assert "$870.00/month" in options[1] and "excludes taxes" in options[1]


def test_recorded_blockers_prioritize_within_threshold():
    data, obs = fixture()
    data["properties"].append({**data["properties"][2], "id": "actionable"})
    obs["actionable"] = dict(obs["fourteen"])
    data["tasks"] = [{"id": "blocker", "title": "Buyer follow-up", "status": "blocked", "links": {"property_id": "actionable"}}]
    plans = portfolio(data, obs)
    assert [p["property_id"] for p in plans][:3] == ["urgent", "actionable", "fourteen"]
    assert "HIGH evidence" in " ".join(plans[1]["reasons"])


def test_two_hour_runtime_saves_portfolio_plans_without_duplicate_items(monkeypatch, tmp_path):
    from dataclasses import replace

    from test_property_sync_preview import property_record, source_row

    from cfh_disposition import property_change_runtime as runtime

    prop = property_record(listed_at=(datetime.now(UTC).date() - timedelta(days=21)).isoformat())
    row = replace(source_row(), marketing_status="yellow")
    monkeypatch.setattr(runtime, "load_baseline_source", lambda *a, **kw: ([row], "fictional"))
    monkeypatch.setattr(runtime, "read_canonical_records", lambda client, entity: [prop] if entity == "properties" else [])
    monkeypatch.setattr("supabase.create_client", lambda *a: SimpleNamespace())
    monkeypatch.setattr("cfh_disposition.property_change_cache.RUNTIME_ROOT", tmp_path)
    secrets = {"GOOGLE_SHEET_ID": "fictional", "SUPABASE_URL": "fictional", "SUPABASE_SERVICE_ROLE_KEY": "fictional"}
    runtime.read_property_changes(secrets, force=True)
    first = runtime.latest_property_check(secrets)
    runtime.read_property_changes(secrets, force=True)
    second = runtime.latest_property_check(secrets)
    assert len(first["stale_inventory"]["disposition_plans"]) == len(second["stale_inventory"]["disposition_plans"]) == 1
    assert not second["stale_inventory"]["new_ids"]
    assert first["inventory_observations"] == {k: {**v, "checked_at": first["inventory_observations"][k]["checked_at"]}
                                             for k, v in second["inventory_observations"].items()}


def test_actual_streamlit_portfolio_attention_and_no_writes(monkeypatch):
    data, obs = fixture()
    calls = []
    def invoke(name, options):
        assert name == "commandcore-crm-core" and options["body"]["action"] == "list"
        calls.append(options)
        return {"ok": True, "records": data.get(options["body"]["entity"], [])}
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(functions=SimpleNamespace(invoke=invoke)))
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *a: detect_property_changes([], [], source_reference="fictional"))
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *a: {
        "inventory_observations": obs,
        "source_coverage": {"tab_count": 6, "source_colors": {"yellow": 12}, "eligible_canonical_yellow": 4, "unresolved_address_rows": 8}})
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/49_CommandCore_Command_Bot.py"))
        page.secrets.update(APP_PASSWORD="fictional", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.session_state.authenticated = True
        page.run()
        for query in ("Give me a plan for every stale property.", "What needs my attention?"):
            page.text_input(key="corepilot_request").set_value(query)
            page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
            assert not page.exception
            captions = " ".join(item.value for item in page.caption)
            assert "12 yellow source candidates" in captions
            assert "Current canonical properties: 6" in captions
            assert "Current yellow / marketed: 4" in captions
            assert "Valid marketing clocks: 4" in captions
            assert "Only 4 validated canonical properties" not in captions
            shown = " ".join(str(x.value) for group in (page.markdown, page.info) for x in group)
            assert all(p + " Fictional Lane" in shown for p in ("ten", "fourteen", "urgent"))
            assert "PROPOSED PLAN" in shown
    finally:
        st.cache_resource.clear()
