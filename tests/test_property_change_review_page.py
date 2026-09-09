from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_property_baseline import source_rows
from test_property_change_runtime import reader as source_reader

from cfh_disposition import property_change_runtime as runtime
from cfh_disposition.property_change_review import record_review_decision

SECRETS = {"GOOGLE_SHEET_ID": "fictional", "SUPABASE_URL": "fictional", "SUPABASE_SERVICE_ROLE_KEY": "fictional"}


@pytest.fixture
def reader(monkeypatch, tmp_path):
    return source_reader.__wrapped__(monkeypatch, tmp_path)


def test_decisions_and_first_evidence_survive_scheduled_runs(reader):
    result = runtime.read_property_changes(SECRETS, force=True)
    event_id = result.changes[0].event_id
    initial = runtime.latest_property_check(SECRETS)["change_evidence"]
    record_review_decision(SECRETS, event_id, "Ignored")
    record_review_decision(SECRETS, event_id, "Ignored")
    repeated = runtime.read_property_changes(SECRETS, force=True)
    status = runtime.latest_property_check(SECRETS)
    assert not repeated.new_events
    assert status["review_decisions"][event_id] == "Ignored"
    assert status["change_evidence"] == initial and len(status["review_history"]) == 1
    record_review_decision(SECRETS, event_id, "Needs investigation")
    assert runtime.latest_property_check(SECRETS)["review_decisions"][event_id] == "Needs investigation"


def test_live_style_review_controls_are_preview_only(reader, monkeypatch):
    monkeypatch.setattr("cfh_disposition.property_change_review.load_baseline_source", lambda secrets: (source_rows(), "fictional"))
    page = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "pages/54_CommandCore_Property_Changes.py"))
    page.secrets.update(SECRETS)
    page.session_state.authenticated = True
    page.run()
    assert not page.exception and page.button(key="apply_property_disabled").disabled
    event_id = page.session_state.property_detection.changes[0].event_id
    page.button(key=f"review_{event_id}").click().run()
    assert not page.exception
    assert page.session_state.property_patch_preview.new_property
    assert page.button(key="apply_property_disabled").disabled
    page.button(key=f"Ignored_{event_id}").click().run()
    assert runtime.latest_property_check(SECRETS)["review_decisions"][event_id] == "Ignored"
    assert not page.exception
    assert page.button(key="apply_property_disabled").disabled
