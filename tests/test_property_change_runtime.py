from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from test_property_baseline import source_rows

from cfh_disposition import property_change_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reader(monkeypatch, tmp_path):
    calls = []
    fail = [False]

    def source(secrets, **kwargs):
        calls.append("sheet read")
        if fail[0]:
            raise RuntimeError("PRIVATE PROVIDER DETAIL")
        return source_rows(), "fictional"

    class Bucket:
        def list(self, entity, options):
            assert entity == "properties"
            calls.append("canonical read")
            return []

    monkeypatch.setattr(runtime, "load_baseline_source", source)
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(storage=SimpleNamespace(from_=lambda name: Bucket())))
    monkeypatch.setattr("cfh_disposition.property_change_cache.RUNTIME_ROOT", tmp_path)
    return calls, fail


def test_page_checks_on_open_and_preserves_checkpoint_on_failed_read(reader):
    calls, fail = reader
    page = AppTest.from_file(str(ROOT / "pages/54_CommandCore_Property_Changes.py"))
    page.session_state.authenticated = True
    page.secrets.update(GOOGLE_SHEET_ID="fictional-sheet", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
    page.run()
    assert not page.exception and not page.error
    assert calls == ["sheet read", "canonical read"]
    assert any(metric.label == "New Property" and metric.value == "1" for metric in page.metric)
    page.selectbox[0].select("NEW PROPERTY").run()
    assert len(calls) == 2
    page.button(key="check_property_changes").click().run()
    assert len(calls) == 4
    assert any("0 newly detected events" in caption.value for caption in page.caption)
    checkpoint = runtime.latest_property_check(page.secrets)["result"]
    fail[0] = True
    page.button(key="check_property_changes").click().run()
    assert any("check failed" in warning.value for warning in page.warning)
    assert not page.exception and runtime.latest_property_check(page.secrets)["result"] == checkpoint
    assert all("PRIVATE" not in warning.value for warning in page.warning)


def test_checkpoint_shared_across_callers_but_scope_isolated(reader):
    first = runtime.read_property_changes({"SUPABASE_URL": "first", "GOOGLE_SHEET_ID": "fictional"}, force=True)
    repeat = runtime.read_property_changes({"SUPABASE_URL": "first", "GOOGLE_SHEET_ID": "fictional"}, force=True)
    other = runtime.read_property_changes({"SUPABASE_URL": "other", "GOOGLE_SHEET_ID": "fictional"}, force=True)
    assert len(first.new_events) == len(other.new_events) == 1
    assert not repeat.new_events


def test_corepilot_real_form_uses_detector_and_exposes_changes(reader, monkeypatch):
    # Existing CorePilot canonical entity reads are transport fixtures; detector
    # still executes the real source adapter and comparison through its reader.
    import json

    import streamlit as st

    class Bucket:
        def list(self, *args):
            return []

    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(
        storage=SimpleNamespace(from_=lambda name: Bucket()),
        functions=SimpleNamespace(invoke=lambda *args: json.dumps({"records": []}).encode())))
    st.cache_resource.clear()
    try:
        page = AppTest.from_file(str(ROOT / "pages/49_CommandCore_Command_Bot.py"))
        page.session_state.authenticated = True
        page.secrets.update(APP_PASSWORD="fictional", GOOGLE_SHEET_ID="fictional-sheet", SUPABASE_URL="fictional", SUPABASE_SERVICE_ROLE_KEY="fictional")
        page.run()
        page.text_input(key="corepilot_request").set_value("What new properties were added?")
        page.button(key="FormSubmitter:corepilot_request_form-Ask CorePilot").click().run()
        assert not page.exception
        assert any("NEW PROPERTY" in item.value for item in page.markdown)
    finally:
        st.cache_resource.clear()
