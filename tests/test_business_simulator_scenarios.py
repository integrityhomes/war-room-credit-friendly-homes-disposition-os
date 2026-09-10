"""Cross-module business-day scenarios using real rules and synthetic I/O only."""

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from cfh_disposition.commandcore_property_inventory import deterministic_property_id
from cfh_disposition.corepilot_inventory import inventory_items, observe_inventory, stale_checkpoint
from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.corepilot_portfolio import portfolio_answer
from cfh_disposition.corepilot_work import manage_work, update_internal_record
from cfh_disposition.google_property_marketing import attach_highlights
from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues
from cfh_disposition.harness.simulation_adapters import FakeCanonicalStore, SimulationClock
from cfh_disposition.property_change_detection import detect_property_changes
from cfh_disposition.property_import_reconciliation import build_current_inventory_candidates
from cfh_disposition.property_marketing_eligibility import marketing_checkpoint_preview
from cfh_disposition.property_sync_preview import INVENTORY_TABS, REGIONAL_TABS, regional_sheet_properties

HEADER = ["Property", "Beds", "Baths", "Sq ft", "Monthly", "Sales price", "Down payment", "Interest rate", "Insurance", "Owner", "Lockbox"]


def synthetic_rows():
    sheets = {name: [HEADER] for name in INVENTORY_TABS}
    colors = {}
    for index in range(29):
        name = REGIONAL_TABS[index % len(REGIONAL_TABS)]
        terms = ["1100", "109000", "4500", "8.5"] if index % 2 else ["925", "89000", "3000", "9.5"]
        row = [f"{1000 + index} Simulation Lane, Fictional City, IL 60000", "3", "2", "1200", *terms,
               "Buyer responsible" if index % 2 else "55", "Fictional Owner A" if index % 2 else "Fictional Owner B", "SYNTHETIC-ACCESS"]
        if index < 12:
            row[3] = "??"
        sheets[name].append(row)
        colors[name, len(sheets[name])] = "yellow" if index < 25 else "white"
    sheets["SOLD"].append(list(sheets[REGIONAL_TABS[0]][1]))
    parsed = regional_sheet_properties([ReadOnlyWorksheetValues(name, rows) for name, rows in sheets.items()], "simulation-only", verified_format_recovery=True)
    return attach_highlights(parsed, colors)


def simulated_import():
    source = synthetic_rows()
    plan = build_current_inventory_candidates(source, [])
    store = FakeCanonicalStore()
    for entry in plan["properties"]:
        assert entry["ready_for_canonical_creation"]
        row = next(r for r in source if (r.tab, r.row) == (entry["source_tab"], entry["source_row"]))
        record = {**row.fields, "id": "simulation-" + deterministic_property_id("simulation", entry["normalized_address"]),
                  "sync_metadata": {"source_fields": row.source_fields}, "source": "cfh-google-sheet"}
        store.create(record)
    return source, plan, store


def test_simulation_29_current_properties_created_once_with_preserved_unknowns():
    source, plan, store = simulated_import()
    assert plan["summary"]["Yellow"]["identity_safe"] == 25
    assert plan["summary"]["White"]["identity_safe"] == 4
    assert len(store.list()) == 29 and plan["historical_only_included"] == 0
    for record in store.list():
        assert store.create(record) is False
    assert store.duplicates_prevented == 29 and len(store.list()) == 29
    assert build_current_inventory_candidates(source, store.list())["total_candidates"] == 0
    uncertain = [r for r in store.list() if any(d["field"] == "square_feet" and d["review"] for d in r["sync_metadata"]["source_fields"])]
    assert len(uncertain) == 12
    assert all(r.get("square_feet") is None and r["bedrooms"] == 3 for r in uncertain)
    assert all(r["asking_or_sale_price"] == ("109000" if r["seller_entity"] == "Fictional Owner A" else "89000") for r in store.list())
    assert "SYNTHETIC-ACCESS" not in json.dumps(plan)


def test_simulation_current_import_execution_path_readiness(tmp_path):
    from test_property_current_import import test_real_current_executor_creates_29_once_and_ages_only_25
    test_real_current_executor_creates_29_once_and_ages_only_25(tmp_path)


def test_simulation_two_missing_clocks_preserve_existing_25_and_repeat():
    source, _, store = simulated_import()
    yellow = [r for r in source if r.tab in REGIONAL_TABS and r.marketing_status == "yellow"]
    # A synthetic portfolio with 27 yellow canonical identities, two untracked.
    additions = [replace(yellow[-1], row=100+i, fields={**yellow[-1].fields, "address": f"{2000+i} Simulation Lane"}) for i in range(2)]
    props = store.list()
    props += [{**r.fields, "id": f"simulation-return-{i}"} for i, r in enumerate(additions)]
    clock = SimulationClock()
    initial = marketing_checkpoint_preview(source, props, {}, observed_at=clock.now.isoformat())
    obs = {e["property_id"]: e["proposed_checkpoint_patch"] for e in initial["eligible"]}
    clock.advance(hours=2)
    result = marketing_checkpoint_preview([*source, *additions], props, obs, observed_at=clock.now.isoformat())
    assert result["missing_count"] == 2 and result["preserved_count"] == 25
    for e in result["eligible"]:
        if e["proposed_checkpoint_patch"]:
            obs[e["property_id"]] = e["proposed_checkpoint_patch"]
    before = copy.deepcopy(obs)
    clock.advance(hours=2)
    repeated = marketing_checkpoint_preview([*source, *additions], props, obs, observed_at=clock.now.isoformat())
    assert repeated["missing_count"] == 0 and repeated["preserved_count"] == 27 and obs == before


@pytest.mark.parametrize("day,expected", [(0, 0), (9, 0), (10, 25), (14, 25), (21, 25), (35, 25)])
def test_simulation_portfolio_clock_and_bot_find_every_marketed_property(day, expected):
    source, _, store = simulated_import()
    clock = SimulationClock()
    plan = marketing_checkpoint_preview(source, store.list(), {}, observed_at=clock.now.isoformat())
    obs = {e["property_id"]: e["proposed_checkpoint_patch"] for e in plan["eligible"]}
    clock.advance(days=day)
    stale = stale_checkpoint(store.list(), obs, today=clock.now.date())
    assert len(stale["attention"]) == expected
    answer = portfolio_answer("Which properties are stale?", {"properties": store.list()}, obs, today=clock.now.date())
    if expected:
        found = " ".join(answer.what_i_found)
        assert all(p["address"] in found for p in stale["attention"]), "Portfolio answer must surface every stale property"


def test_simulation_scheduled_observer_does_not_drop_verified_yellow_with_detail_warnings():
    source, _, store = simulated_import()
    clock = SimulationClock()
    obs = observe_inventory(source, store.list(), checked_at=clock.now.isoformat())
    yellow = [p for p in inventory_items(store.list(), obs, today=clock.now.date()) if p["marketing_status"] == "yellow"]
    assert len(yellow) == 25, "Existing scheduled observer must not discard yellow identities because of optional detail errors"


def test_simulation_portfolio_term_changes_and_adapter_failure():
    source, _, store = simulated_import()
    props = store.list()
    before = copy.deepcopy(props)
    initial = detect_property_changes(source, props, source_reference="simulation", lockbox_key="simulation-only")
    changed = [replace(r, fields={**r.fields, "asking_or_sale_price": "84900", "monthly_payment": "895", "down_payment": "2500", "interest_rate": "8.5"})
               if r.marketing_status == "yellow" and not r.issues else r for r in source]
    later = detect_property_changes(changed, props, source_reference="simulation", previous=initial.state, lockbox_key="simulation-only")
    again = detect_property_changes(changed, props, source_reference="simulation", previous=later.state, lockbox_key="simulation-only")
    assert not again.new_events and not again.observed_new_events
    assert props == before
    store.fail_next = True
    with pytest.raises(TimeoutError):
        store.create({"id": "simulation-failure"})
    assert store.list() == before


def test_simulation_full_business_day_with_shared_canonical_fixture():
    source, _, store = simulated_import()
    clock = SimulationClock()
    props = store.list()
    protected = copy.deepcopy(props)
    eligible = marketing_checkpoint_preview(source, props, {}, observed_at=clock.now.isoformat())
    observations = {e["property_id"]: e["proposed_checkpoint_patch"] for e in eligible["eligible"]}
    clock.advance(days=21)
    data = {"properties": props, "deals": [], "activities": [], "approvals": [],
            "tasks": [{"id": "simulation-task", "title": "Review buyer inquiry", "assigned_to": "Fictional Alex",
                       "internal_only": True, "due_date": "2035-01-20", "status": "open", "links": {"property_id": props[0]["id"]}}],
            "contacts": [{"id": "simulation-worker", "assigned_to": "Fictional Jordan"}],
            "communications": [{"id": "simulation-draft", "direction": "outbound_draft", "status": "draft",
                                "internal_only": True, "body": "Please confirm your question.", "send_enabled": False,
                                "links": {"property_id": props[0]["id"]}}]}

    # Transport only: authorization, stale-read protection and audit/history remain real.
    def invoke(name, options):
        assert name == "commandcore-crm-core"
        body = options["body"]
        assert body["entity"] in {"tasks", "communications"}
        identity = body.get("id") or body.get("record", {}).get("id")
        record = next(r for r in data[body["entity"]] if r["id"] == identity)
        if body["action"] == "upsert":
            record.update(copy.deepcopy(body["record"]))
        else:
            assert body["action"] == "get"
        return {"ok": True, "record": copy.deepcopy(record)}

    client = SimpleNamespace(functions=SimpleNamespace(invoke=invoke))

    def updater(entity, expected, patch, actor):
        return update_internal_record(client, entity, expected, patch, actor)

    morning = stale_checkpoint(props, observations, today=clock.now.date())
    assert len(morning["attention"]) == 25
    for query in ("What needs my attention?", "What approvals are waiting?", "Which communications need a response?"):
        answer = run_corepilot(query, data)
        assert answer.external_actions_started == answer.records_written == 0
    context = {}
    for command in ("What work does Fictional Alex have?", "Move that to Friday.", "Give it to Fictional Jordan.",
                    "Add a note that we are waiting on the seller.", "Show the private draft", "Revise that draft with Thank you for the inquiry"):
        result = manage_work(command, data, context, updater, today=clock.now.date())
        assert result is not None and not result.clarification
        context = dict(result.context)
        assert result.external_actions_started == 0
    assert len(data["tasks"][0]["internal_history"]) == 3
    assert data["communications"][0]["status"] == "draft" and data["communications"][0]["send_enabled"] is False

    # Afternoon source states, never mutations to canonical property facts.
    valid = [r for r in source if r.marketing_status == "yellow" and not r.issues]
    first, second = valid[:2]
    sold = [replace(r, fields={**r.fields, "availability": "Sold / unavailable"}) if r == first else r for r in source]
    late = observe_inventory(sold, props, observations, checked_at=clock.now.isoformat())
    clock.advance(hours=2)
    returned = observe_inventory(source, props, late, checked_at=clock.now.isoformat())
    first_id = next(p["id"] for p in props if p["address"] == first.fields["address"])
    assert late[first_id]["status"] != "available"
    assert returned[first_id]["marketing_observed_since"] == clock.now.isoformat()
    changed = [replace(r, fields={**r.fields, "monthly_payment": "875"}) if r == second else r for r in source]
    detection = detect_property_changes(changed, props, source_reference="simulation", lockbox_key="simulation-only")
    repeated = detect_property_changes(changed, props, source_reference="simulation", previous=detection.state, lockbox_key="simulation-only")
    assert not repeated.new_events
    recommendations = portfolio_answer("What should we do to get these sold?", data, observations, today=clock.now.date())
    assert recommendations.recommended_next_step and recommendations.records_written == 0
    assert props == protected


@pytest.mark.parametrize("layout", range(76))
def test_simulation_all_76_header_layouts_use_real_parser(layout):
    headers = json.loads((Path(__file__).parent / "fixtures/simulation_workbook_layouts.json").read_text())["layouts"][layout]
    values = [""] * len(headers)
    values[0] = "3000 Simulation Lane, Fictional City, IL 60000"
    for i, header in enumerate(headers):
        if header in {"beds", "baths"}:
            values[i] = "2"
    sheets = [ReadOnlyWorksheetValues(tab, [headers, values] if tab == REGIONAL_TABS[layout % 11] else [HEADER]) for tab in INVENTORY_TABS]
    parsed = regional_sheet_properties(sheets, "simulation", verified_format_recovery=True)
    assert len(parsed) == 1 and parsed[0].fields["city"] == "Fictional City"
    assert len(parsed[0].source_fields) >= sum(bool(h) for h in headers)
