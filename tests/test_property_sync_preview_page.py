import json
from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from cfh_disposition import google_property_readonly_loader, google_property_runtime_bridge
from cfh_disposition.google_property_readonly_loader import ReadOnlyWorksheetValues
from cfh_disposition.property_sync_preview import INVENTORY_TABS
from supabase import __name__ as _supabase_name

ROOT = Path(__file__).resolve().parents[1]


def test_page_submits_through_real_adapter_comparison_and_read_only_storage(monkeypatch):
    calls = []
    fail = [False]

    def read_sheet(*args):
        calls.append("sheet read")
        if fail[0]:
            raise RuntimeError("private provider error must not appear")
        row = ["101 Example Lane, Example City, IL 60000", "", "3", "2", "1200", "5000", "900", "110000"]
        header = ["Property", "Lock box code", "Beds", "Baths", "Sq Ft", "Down Payment", "Monthly", "Sales Price"]
        return tuple(ReadOnlyWorksheetValues(tab, [header, row] if index == 0 else []) for index, tab in enumerate(INVENTORY_TABS))

    class Bucket:
        def list(self, entity, options):
            calls.append(entity)
            return [{"name": "fictional.json"}] if entity == "properties" else []

        def download(self, path):
            return json.dumps({"id": "existing-property", "address": "101 Example Lane", "city": "Example City", "state": "IL",
                               "zip": "60000", "asking_price": "100000", "availability": "Available"}).encode()

    def from_bucket(name):
        assert name == "commandcore-crm-core"
        return Bucket()

    monkeypatch.setattr(google_property_runtime_bridge, "resolve_read_only_google_access", lambda *args: (object(), "fictional-sheet"))
    monkeypatch.setattr(google_property_readonly_loader, "load_all_read_only_worksheet_values", read_sheet)
    monkeypatch.setattr(f"{_supabase_name}.create_client", lambda *args: SimpleNamespace(storage=SimpleNamespace(from_=from_bucket)))
    app = AppTest.from_string(
        "import streamlit as st\n"
        "st.navigation(["
        f"st.Page({str(ROOT / 'pages/52_CommandCore_Property_Sync_Preview.py')!r}, default=True),"
        f"st.Page({str(ROOT / 'pages/53_CommandCore_Property_Baseline.py')!r})"
        "], position='hidden').run()"
    )
    app.secrets.update({"APP_PASSWORD": "fictional-only", "SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional"})
    app.session_state["authenticated"] = True
    app.run()
    assert calls == []
    app.button(key="build_sync_preview").click().run()
    assert not app.exception and not app.error
    assert calls == ["sheet read", "properties", "deals"]
    assert any(metric.label == "Price Change" and metric.value == "1" for metric in app.metric)
    assert any("Records changed: 0" in item.value for item in app.caption)
    assert [button.label for button in app.button] == ["Build read-only preview"]
    app.selectbox[0].select("PRICE CHANGE").run()
    assert calls == ["sheet read", "properties", "deals"]
    fail[0] = True
    app.button(key="build_sync_preview").click().run()
    assert not app.exception
    assert app.error and not app.metric
    assert "private provider" not in app.error[0].value


def test_page_is_registered_in_daily_deal_navigation():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'NavigationItem("pages/52_CommandCore_Property_Sync_Preview.py", "Property Sync Preview")' in source
    assert 'st.Page("pages/52_CommandCore_Property_Sync_Preview.py", title="Property Sync Preview"' in source
