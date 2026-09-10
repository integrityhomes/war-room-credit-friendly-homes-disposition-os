"""Authenticated real-page scenarios; transports only are replaced."""

import copy
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib import request
from urllib.parse import urlparse

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from cfh_disposition.sample_data import SAMPLE_BUYERS, SAMPLE_PROPERTIES
from cfh_disposition.storage import InMemoryStorage

ROOT = Path(__file__).resolve().parents[1]
REVIEW = (ROOT / "docs/simulator-coverage-review.md").read_text(encoding="utf-8")
GAP_PATHS = [line.split("`")[1] for line in REVIEW.splitlines() if line.startswith("| `")]
PAGE_PATHS = [p for p in GAP_PATHS if p.startswith("pages/") or p == "app.py"]


class PageTransport:
    """Synthetic transport responses, never a copy of server business rules."""

    def __init__(self):
        self.calls, self.denied = [], []
        self.allow_internal = False
        self.exceptions = [{"exception_id": "simulation-exception", "id": "simulation-exception", "status": "open", "aging_level": "executive",
                            "severity": "critical", "summary": "Fictional coverage gap", "created_at": "2030-01-01", "owner": "Fictional Alex"}]
        self.dispatch = {"dispatch_id": "simulation-dispatch", "items": [{"action_id": "simulation-action", "property_id": "simulation-property",
                         "channel_key": "facebook_groups", "status": "open", "priority": "high", "owner_id": "simulation-worker",
                         "owner_name": "Fictional Alex", "title": "Fictional manual review", "assigned_to": "Fictional Alex"}]}
        self.data = {
            "properties": [{"id": "simulation-property", "address": "101 Example Lane", "city": "Example City", "state": "IL", "zip": "60000", "availability": "Available"}],
            "contacts": [{"id": "simulation-contact", "name": "Fictional Seller", "first_name": "Fictional", "last_name": "Seller", "contact_type": "Seller"}],
            "deals": [{"id": "simulation-deal", "title": "Fictional purchase", "name": "Fictional purchase", "stage": "Follow-Up", "status": "Active",
                       "links": {"property_id": "simulation-property", "contact_id": "simulation-contact"}}],
            "tasks": [{"id": "simulation-task", "title": "Fictional follow-up", "assigned_to": "Fictional Alex", "due_date": "2030-01-01", "status": "open",
                       "internal_only": True, "links": {"property_id": "simulation-property", "deal_id": "simulation-deal"}}],
            "communications": [{"id": "simulation-message", "direction": "inbound", "channel": "email", "body": "Please confirm the next step.", "status": "needs_response",
                                 "links": {"contact_id": "simulation-contact", "property_id": "simulation-property", "deal_id": "simulation-deal"}}],
            "offers": [{"id": "simulation-offer", "status": "draft_pending_owner_approval", "title": "Fictional offer review", "links": {"deal_id": "simulation-deal"}}],
        }

    def invoke(self, name, options):
        body = options.get("body", {})
        self.calls.append((name, body.get("action", "")))
        if self.allow_internal and name == "commandcore-crm-core" and body.get("action") == "upsert" and body.get("entity") in {"tasks", "communications"}:
            record = next(r for r in self.data[body["entity"]] if r["id"] == body["record"]["id"])
            record.update(copy.deepcopy(body["record"]))
            return {"ok": True, "record": copy.deepcopy(record)}
        if body.get("action", "") not in {"", "list", "get", "summary", "evaluate_contact", "preview", "analyze", "status", "report"}:
            self.denied.append((name, body.get("action")))
            raise AssertionError("Unexpected action in read-only surface scenario")
        records = copy.deepcopy(self.data.get(body.get("entity"), []))
        return {"ok": True, "records": records, "record": next((r for r in records if r["id"] == body.get("id")), {}),
                "items": [], "members": [{"id": "simulation-worker", "name": "Fictional Alex", "active": True}],
                "exceptions": self.exceptions, "approvals": [], "recommendations": [], "launch_ready": False,
                "summary": {}, "allowed": False, "send_enabled": False}

    def bucket(self, name):
        owner = self

        class Bucket:
            def list(self, prefix="", options=None):
                owner.calls.append((name, "storage-list"))
                if name == "commandcore-crm-core":
                    return [{"name": r["id"] + ".json"} for r in owner.data.get(prefix, [])]
                if name == "commandcore-action-queue" and prefix == "dispatches":
                    return [{"name": "simulation-dispatch.json"}]
                return []

            def download(self, path):
                if name == "commandcore-action-queue" and path == "dispatches/simulation-dispatch.json":
                    return json.dumps(owner.dispatch).encode()
                if name == "commandcore-crm-core" and "/" in path:
                    entity, key = path.split("/", 1)
                    row = next((r for r in owner.data.get(entity, []) if r["id"] + ".json" == key), None)
                    if row:
                        return json.dumps(row).encode()
                raise FileNotFoundError("No synthetic ledger yet")

            def upload(self, *args, **kwargs):
                if owner.allow_internal and name == "commandcore-crm-core":
                    path, payload = args[:2]
                    entity = path.split("/")[0]
                    assert entity in {"tasks", "communications", "activities"}
                    assert kwargs["file_options"]["upsert"] == "false"
                    record = json.loads(payload)
                    assert record["internal_only"] is True
                    if any(r["id"] == record["id"] for r in owner.data.get(entity, [])):
                        raise FileExistsError("Synthetic create-only collision")
                    owner.data.setdefault(entity, []).append(record)
                    return
                owner.denied.append((name, "upload"))
                raise AssertionError("Page read must not write")

        return Bucket()

    def urlopen(self, req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert urlparse(url).hostname == "simulation.invalid"
        body = json.loads(req.data or b"{}") if hasattr(req, "data") else {}
        if "/functions/v1/" in url:
            payload = self.invoke(url.rsplit("/", 1)[-1], {"body": body})
        else:
            self.denied.append(("unexpected-http", urlparse(url).path))
            raise AssertionError("Unconfigured fake transport")
        return io.BytesIO(json.dumps(payload).encode())


@pytest.fixture
def surfaces(monkeypatch):
    backend = PageTransport()
    storage = InMemoryStorage(SAMPLE_PROPERTIES, SAMPLE_BUYERS)
    client = SimpleNamespace(storage=SimpleNamespace(from_=backend.bucket, get_bucket=lambda name: {"public": False}),
                             functions=SimpleNamespace(invoke=backend.invoke))
    original = request.urlopen
    monkeypatch.setattr(request, "urlopen", backend.urlopen)
    for name, module in list(sys.modules.items()):
        if name.startswith("cfh_disposition") and getattr(module, "urlopen", None) is original:
            monkeypatch.setattr(module, "urlopen", backend.urlopen)
    monkeypatch.setattr("supabase.create_client", lambda *args, **kwargs: client)
    monkeypatch.setattr("cfh_disposition.storage.build_storage", lambda *args: storage)
    # AppTest's generated entrypoint lives in its isolated temp directory. Resolve
    # real root-relative page links exactly as app.py does, retaining navigation.
    for method in ("page_link", "switch_page"):
        original_navigation = getattr(st, method)

        def navigate(page, *args, _original=original_navigation, **kwargs):
            if isinstance(page, str) and page.startswith("pages/"):
                page = str(ROOT / page)
            return _original(page, *args, **kwargs)

        monkeypatch.setattr(st, method, navigate)
    from streamlit.delta_generator import DeltaGenerator
    original_link = DeltaGenerator.page_link

    def column_link(self, page, *args, **kwargs):
        if isinstance(page, str) and page.startswith("pages/"):
            page = str(ROOT / page)
        return original_link(self, page, *args, **kwargs)

    monkeypatch.setattr(DeltaGenerator, "page_link", column_link)
    st.cache_resource.clear()
    st.cache_data.clear()
    yield backend, storage
    st.cache_resource.clear()
    st.cache_data.clear()


def page_for(path):
    if path == "app.py":
        app = AppTest.from_file(str(ROOT / path), default_timeout=30)
    else:
        paths = sorted((ROOT / "pages").glob("*.py"))
        navigation = ",".join(f"st.Page({str(p)!r}, default={p == ROOT / path!r})" for p in paths)
        app = AppTest.from_string("import streamlit as st\nst.navigation([" + navigation + "], position='hidden').run()", default_timeout=30)
    app.secrets.update(APP_PASSWORD="simulation-only", SUPABASE_URL="https://simulation.invalid", SUPABASE_SERVICE_ROLE_KEY="fictional")
    app.session_state.authenticated = True
    app.session_state.commandcore_selected_deal_id = "simulation-deal"
    return app


@pytest.mark.parametrize("path", PAGE_PATHS)
def test_current_surface_renders_authenticated_synthetic_business_state(surfaces, path):
    backend, storage = surfaces
    before = copy.deepcopy(backend.data)
    properties = [p.model_dump(mode="json") for p in storage.list_properties()]
    app = page_for(path).run()
    assert not app.exception, [e.message for e in app.exception]
    expected_errors = {
        "pages/49_CommandCore_Phone_System_Setup.py": ["NO LIVE CALLS OR TEXTS NO EXTERNAL PHONE ACTIONS"],
        "pages/39_CommandCore_Operations_Hub.py": ["1 coverage issue(s) require executive attention before normal queue work.",
                                                  "CommandCore is not launch-ready. Required service failures need attention before relying on automation."],
        "pages/37_CommandCore_Coverage_Exceptions.py": ["Executive attention: this unresolved coverage problem has aged past the highest escalation threshold."],
    }
    errors = [" ".join(e.value.split()) for e in app.error]
    assert errors == expected_errors.get(path, []), errors
    assert app.title or app.header or app.markdown
    assert not backend.denied, backend.denied
    assert backend.data == before
    assert [p.model_dump(mode="json") for p in storage.list_properties()] == properties


def test_canonical_task_is_visible_in_my_work(surfaces):
    backend, _ = surfaces
    app = page_for("pages/35_CommandCore_My_Work.py").run()
    assert not app.exception
    rendered = " ".join(x.value for kind in (app.markdown, app.caption) for x in kind)
    assert backend.data["tasks"][0]["title"] in rendered


def test_management_exception_moves_between_alert_and_team_surfaces(surfaces):
    backend, _ = surfaces
    for path in ("pages/37_CommandCore_Coverage_Exceptions.py", "pages/38_CommandCore_Management_Alerts.py", "pages/40_CommandCore_Team_Health.py"):
        app = page_for(path).run()
        assert not app.exception
    alerts = page_for("pages/38_CommandCore_Management_Alerts.py").run()
    assert any(m.label == "Needs Management" and m.value == "1" for m in alerts.metric)
    backend.exceptions[0]["status"] = "resolved"  # Synthetic upstream response changes.
    cleared = page_for("pages/38_CommandCore_Management_Alerts.py").run()
    assert any(m.label == "Needs Management" and m.value == "0" for m in cleared.metric)
    assert not backend.denied


def test_shared_property_deal_contact_communication_and_approval_views(surfaces):
    backend, _ = surfaces
    for path in ("pages/44_CommandCore_CRM.py", "pages/45_CommandCore_Deal_Record.py", "pages/51_CommandCore_Communications.py", "pages/48_CommandCore_Owner_Approvals.py"):
        app = page_for(path).run()
        assert not app.exception
    entities = {entity for entity in backend.data}
    assert {"properties", "deals", "contacts", "communications", "offers"} <= entities
    assert backend.data["offers"][0]["status"] == "draft_pending_owner_approval"
    assert not backend.denied
    approvals = page_for("pages/48_CommandCore_Owner_Approvals.py").run()
    assert any(m.label == "Offers" and m.value == "1" for m in approvals.metric)
    messages = page_for("pages/51_CommandCore_Communications.py").run()
    assert "101 Example Lane" in " ".join(m.value for m in messages.markdown)
    assert any(m.label == "In this view" and m.value == "1" for m in messages.metric)


@pytest.mark.parametrize("query", ["What needs my attention?", "What properties changed?", "What properties are stale?",
    "What work is overdue?", "What approvals are waiting?", "What deals need attention?", "What communications need responses?",
    "What should we work on first?", "What is the most important thing right now?", "What should my team work on first?", "Prioritize today's work.", "What needs to happen first?",
    "What changed with this property?", "What is holding this deal up?"])
def test_real_command_bot_routes_across_shared_business_records(surfaces, monkeypatch, query):
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    from test_property_sync_preview import source_row

    from cfh_disposition.corepilot_inventory import observe_inventory
    from cfh_disposition.property_change_detection import detect_property_changes

    backend, _ = surfaces
    properties = backend.data["properties"]
    properties[0].update(asking_or_sale_price="100000", monthly_payment="900")
    backend.data["tasks"][0]["due_date"] = "2000-01-01"
    row = replace(source_row(asking_or_sale_price="95000"), marketing_status="yellow")
    detector = detect_property_changes([row], properties, source_reference="simulation")
    observations = observe_inventory([row], properties, checked_at=(datetime.now(UTC) - timedelta(days=21)).isoformat())
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *args, **kwargs: detector)
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *args: {"inventory_observations": observations})
    from cfh_disposition import corepilot_internal
    captured = []
    original = corepilot_internal.run_internal_command

    from functools import wraps

    @wraps(original)
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(corepilot_internal, "run_internal_command", capture)
    app = page_for("pages/49_CommandCore_Command_Bot.py")
    app.session_state.corepilot_context = {"property_id": "simulation-property", "deal_id": "simulation-deal", "contact_id": "simulation-contact"}
    app.run()
    app.text_input(key="corepilot_request").set_value(query)
    app.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
    assert not app.exception and not backend.denied
    result = captured[-1]
    assert not result.clarification, result.clarification
    assert result.records_written == result.external_actions_started == 0


def test_marketing_home_readiness_and_record_manager_use_shared_records(surfaces):
    _, storage = surfaces
    original = [p.model_dump(mode="json") for p in storage.list_properties()]
    app = page_for("pages/90_CFH_Marketing_Dispo.py").run()
    for section in ("Campaign Readiness", "More Tools"):
        app.selectbox(key="main_navigation").set_value(section).run()
        assert not app.exception
    for tool in app.selectbox(key="advanced_tool").options:
        app.selectbox(key="advanced_tool").set_value(tool).run()
        assert not app.exception and not app.error
    assert [p.model_dump(mode="json") for p in storage.list_properties()] == original


def test_facebook_failure_scan_writes_only_synthetic_failure_ledger_and_deduplicates(monkeypatch):
    from cfh_disposition.facebook_failure_scan import scan_facebook_operational_failures
    from cfh_disposition.facebook_groups import FACEBOOK_GROUP_BUCKET, FACEBOOK_GROUP_LEDGER_PATH, FacebookGroupLedger, FacebookGroupRecord
    from cfh_disposition.operational_failures import FAILURE_BUCKET, OperationalFailureStore

    saved = {(FACEBOOK_GROUP_BUCKET, FACEBOOK_GROUP_LEDGER_PATH): FacebookGroupLedger(groups=[FacebookGroupRecord(name="Fictional missing-link group")]).model_dump_json().encode()}

    class Bucket:
        def __init__(self, name):
            self.name = name

        def download(self, path):
            if (self.name, path) not in saved:
                raise FileNotFoundError
            return saved[self.name, path]

        def upload(self, *, path, file, file_options):
            assert self.name == FAILURE_BUCKET
            saved[self.name, path] = file

    client = SimpleNamespace(storage=SimpleNamespace(get_bucket=lambda name: {"public": False}, from_=Bucket))
    monkeypatch.setattr("supabase.create_client", lambda *args: client)
    settings = {"SUPABASE_URL": "https://simulation.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional"}
    assert scan_facebook_operational_failures(settings, SAMPLE_PROPERTIES) == 1
    assert scan_facebook_operational_failures(settings, SAMPLE_PROPERTIES) == 0
    ledger = OperationalFailureStore(settings).load()
    assert len(ledger.failures) == 1 and "missing its saved URL" in ledger.failures[0].summary


def test_source_change_attention_bot_task_completion_and_private_draft_chain(surfaces, monkeypatch):
    from dataclasses import replace

    from test_property_sync_preview import source_row

    from cfh_disposition.property_change_detection import detect_property_changes

    backend, _ = surfaces
    backend.allow_internal = True
    backend.data["contacts"][0]["assigned_to"] = "Fictional Alex"
    backend.data["contacts"][0].update(relationship="seller", email_consent=True, email="fictional@example.test")
    backend.data["communications"][0]["body"] = "Checking in for an update"
    backend.data["properties"][0].update(asking_or_sale_price="100000", monthly_payment="900")
    backend.data["tasks"] = []
    protected = copy.deepcopy({key: backend.data[key] for key in ("properties", "deals", "contacts", "offers")})
    row = replace(source_row(asking_or_sale_price="95000"), marketing_status="yellow")
    changes = detect_property_changes([row], backend.data["properties"], source_reference="simulation")
    assert changes.new_events
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *args, **kwargs: changes)
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *args: {})
    app = page_for("pages/49_CommandCore_Command_Bot.py").run()

    def ask(query):
        app.text_input(key="corepilot_request").set_value(query)
        app.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
        assert not app.exception and not backend.denied

    ask("What properties changed?")
    assert "95000" in "".join(m.value.replace(",", "") for m in app.markdown)
    ask("Find 101 Example Lane")
    ask("Have Fictional Alex follow up tomorrow.")
    assert len(backend.data["tasks"]) == 1
    ask("Have Fictional Alex follow up tomorrow.")
    assert len(backend.data["tasks"]) == 1
    ask("What work does Fictional Alex have?")
    ask("Add a note that we are reviewing the source change.")
    ask("Mark it done.")
    assert backend.data["tasks"][0]["status"] == "done"
    assert backend.data["tasks"][0]["internal_history"]
    ask("Draft a reply.")
    drafts = [m for m in backend.data["communications"] if m.get("direction") == "outbound_draft"]
    assert len(drafts) == 1 and drafts[0]["status"] == "draft"
    before_send = copy.deepcopy(backend.data)
    ask("Send that draft.")
    assert backend.data == before_send
    approvals = page_for("pages/48_CommandCore_Owner_Approvals.py").run()
    assert any(m.label == "Offers" and m.value == "1" for m in approvals.metric)
    assert {key: backend.data[key] for key in protected} == protected


def test_priority_to_canonical_task_all_work_views_share_updates(surfaces, monkeypatch):
    from cfh_disposition.property_change_detection import detect_property_changes

    backend, _ = surfaces
    backend.allow_internal = True
    backend.data["tasks"] = []
    backend.data["contacts"][0]["assigned_to"] = "Sabrina"
    backend.data["properties"][0]["assigned_to"] = "Gabe"
    protected = copy.deepcopy({k: v for k, v in backend.data.items() if k != "tasks"})
    changes = detect_property_changes([], [], source_reference="simulation")
    monkeypatch.setattr("cfh_disposition.property_change_runtime.read_property_changes", lambda *a, **kw: changes)
    monkeypatch.setattr("cfh_disposition.property_change_runtime.latest_property_check", lambda *a: {})
    app = page_for("pages/49_CommandCore_Command_Bot.py").run()

    def ask(query):
        app.text_input(key="corepilot_request").set_value(query)
        app.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
        assert not app.exception and not backend.denied

    def check_views(completed=False):
        expected = backend.data["tasks"][0]
        for name in ("35_CommandCore_My_Work", "39_CommandCore_Operations_Hub", "40_CommandCore_Team_Health", "41_CommandCore_Workload_Balance"):
            view = page_for(f"pages/{name}.py").run()
            assert not view.exception
            assert any(m.label == "Open internal tasks" and m.value == ("0" if completed else "1") for m in view.metric)
            if completed:
                view.checkbox(key="canonical_work_completed").check().run()
            tables = [d.value for d in view.dataframe if "Task ID" in d.value.columns]
            assert len(tables) == 1
            found = tables[0].to_dict("records")
            assert len(found) == 1 and found[0]["Task ID"] == expected["id"]
            assert found[0]["Assigned to"] == expected["assigned_to"]
            assert found[0]["Status"] == expected["status"]
            assert found[0]["Due"] == (expected["due_date"] or "Not specified")
            for note in expected.get("internal_notes", []):
                assert note["text"] in " ".join(m.value for m in view.markdown)

    ask("What should we work on first?")
    assert "1. " in " ".join(m.value for m in app.markdown)
    ask("Give that follow-up to Sabrina.")
    assert len(backend.data["tasks"]) == 1
    task_id = backend.data["tasks"][0]["id"]
    ask("Give that follow-up to Sabrina.")
    assert len(backend.data["tasks"]) == 1
    ask("What work does Sabrina have?")
    check_views()
    ask("Move that to Friday.")
    assert backend.data["tasks"][0]["due_date"]
    check_views()
    ask("Give it to Gabe.")
    assert backend.data["tasks"][0]["assigned_to"] == "Gabe"
    check_views()
    ask("Add a note that we are waiting on the seller.")
    check_views()
    ask("Mark it done.")
    check_views(completed=True)
    assert len(backend.data["tasks"]) == 1 and backend.data["tasks"][0]["id"] == task_id
    assert len(backend.data["tasks"][0]["internal_history"]) == 4
    assert {k: backend.data[k] for k in protected} == protected
    assert not backend.denied


def test_priority_empty_and_invalid_due_dates_do_not_invent_work():
    from cfh_disposition.corepilot_priority import priority_answer

    result = priority_answer({})
    assert "Nothing" in result.what_i_found[0]
    result = priority_answer({"tasks": [{"id": "synthetic", "title": "Undated", "due_date": "unknown"}]})
    assert "Nothing" in result.what_i_found[0]
    assert not result.context and result.records_written == result.external_actions_started == 0
