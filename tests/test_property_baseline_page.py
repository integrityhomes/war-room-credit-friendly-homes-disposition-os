from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from cfh_disposition import google_property_runtime_bridge
from cfh_disposition.property_sync_preview import INVENTORY_TABS

ROOT = Path(__file__).resolve().parents[1]


def test_preimport_page_executes_real_pipeline_with_only_batch_and_canonical_reads(monkeypatch):
    calls = []
    fail = [False]
    header = ["Property", "Lock box code", "Beds", "Baths", "Sq Ft", "Down Payment", "Monthly", "Sales Price"]
    ranges = []
    for tab in (*INVENTORY_TABS, "_REIBB_CACHE"):
        rows = [header]
        indices = range(29) if tab == INVENTORY_TABS[0] else range(29, 155) if tab == "SOLD" else ()
        rows.extend([f"{1000 + index} Example Lane, Example City, IL 60000", "", "3", "2", "1200", "5000", "900", "100000"] for index in indices)
        if tab == INVENTORY_TABS[0]:
            rows.extend([f"Unrecognized item {index}"] for index in range(300))
        ranges.append({"values": rows})

    class ReadOnlySession:
        def __init__(self, credentials):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, *, params, timeout):
            calls.append("sheet batch read")
            assert url.endswith("/values:batchGet")
            assert len([value for key, value in params if key == "ranges"]) == len(INVENTORY_TABS) + 1
            if fail[0]:
                raise RuntimeError("Private provider detail")
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"valueRanges": ranges})

    class Bucket:
        def list(self, entity, options):
            calls.append("canonical read")
            assert entity == "properties"
            return []

    def bucket(name):
        assert name == "commandcore-crm-core"
        return Bucket()

    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", ReadOnlySession)
    monkeypatch.setattr(google_property_runtime_bridge, "resolve_read_only_google_access", lambda *args: (object(), "fictional-sheet"))
    monkeypatch.setattr("supabase.create_client", lambda *args: SimpleNamespace(storage=SimpleNamespace(from_=bucket)))
    app = AppTest.from_file(str(ROOT / "pages/53_CommandCore_Property_Baseline.py"))
    app.secrets.update({"APP_PASSWORD": "fictional-only", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional"})
    app.session_state["authenticated"] = True
    app.run()
    assert not calls
    assert any("reference counts are not a live read" in item.value for item in app.caption)
    app.button(key="build_property_baseline").click().run()
    assert not app.exception and not app.error
    assert calls == ["sheet batch read", "canonical read"]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Properties proposed for creation"] == "155"
    assert metrics["Active inventory"] == "29"
    assert metrics["Source-classified sold / unavailable"] == "126"
    assert metrics["Skipped Needs Review"] == "300"
    assert metrics["Deletions"] == metrics["Errors"] == "0"
    assert app.button(key="baseline_import_disabled").disabled
    app.selectbox[0].select(1).run()
    assert len(calls) == 2
    fail[0] = True
    app.button(key="build_property_baseline").click().run()
    assert not app.exception and app.error and not app.metric
    assert "Private provider" not in app.error[0].value
    assert any("RuntimeError" in item.value and "get:" in item.value for item in app.code)
    assert all("Private provider" not in item.value for item in app.code)


def test_final_baseline_is_reachable_and_has_no_import_call():
    page = (ROOT / "pages/53_CommandCore_Property_Baseline.py").read_text(encoding="utf-8")
    assert "import_baseline(" not in page
    assert 'disabled=True, key="baseline_import_disabled"' in page
    assert 'st.Page("pages/53_CommandCore_Property_Baseline.py"' in (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'label="Final baseline preview"' in (ROOT / "pages/52_CommandCore_Property_Sync_Preview.py").read_text(encoding="utf-8")
