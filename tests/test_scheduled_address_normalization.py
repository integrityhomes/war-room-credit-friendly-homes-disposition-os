"""Actual scheduled pipeline with fictional Google/CRM transport responses."""

import json
from types import SimpleNamespace

import pytest

from cfh_disposition import property_change_runtime as runtime
from cfh_disposition.property_baseline import load_baseline_source
from cfh_disposition.property_change_cache import cache_path, read_cache
from cfh_disposition.property_sync_preview import INVENTORY_TABS


@pytest.mark.parametrize("source_address", ["101 N Example St Example City, Illinois 60000", "101 N Example St., Example City, IL. 60000"])
def test_scheduled_reader_full_state_name_keeps_unique_match_and_clock(monkeypatch, tmp_path, source_address):
    calls = []
    header = ["Property", "Lock box code", "Beds", "Baths", "Sq Ft", "Down Payment", "Monthly", "Sales Price", "Fair cash value", "Assessed value"]
    addresses = [source_address, "202 Fiction Lane, Example City, IL 60000"]
    properties = [{"id": f"fictional-{i}", "address": street, "city": "Example City", "state": "IL", "zip": "60000",
                   "availability": "Available", "source": "cfh-google-sheet"}
                  for i, street in enumerate(("101 N Example St", "202 Fiction Lane"))]

    class Session:
        def __init__(self, credentials):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, *, params, timeout):
            calls.append(url.rsplit("/", 1)[-1])
            values = [header, *[[a, "", "3", "2", "1200", "5000", "900", "100000", "ambiguous value", "unverified value"] for a in addresses]]
            if url.endswith("/values:batchGet"):
                data = {"valueRanges": [{"values": values if i == 0 else []} for i, _ in enumerate(INVENTORY_TABS)]}
            elif isinstance(params, list):
                data = {"sheets": [{"properties": {"title": name}, "data": [{"rowData": [
                    {"values": [{"formattedValue": str(v), "effectiveFormat": {"backgroundColor": {"red": 1, "green": 1}}}
                                for v in row]} for row in (values if i == 0 else [])]}]}
                                   for i, name in enumerate(INVENTORY_TABS)]}
            else:
                data = {"sheets": [{"properties": {"title": name}} for name in INVENTORY_TABS]}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

    class Bucket:
        def list(self, entity, options):
            return [{"name": p["id"] + ".json"} for p in properties] if entity == "properties" else []

        def download(self, path):
            return json.dumps(next(p for p in properties if path == f"properties/{p['id']}.json")).encode()

        def upload(self, *args, **kwargs):
            raise AssertionError("Scheduled check cannot write canonical records")

    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Session)
    monkeypatch.setattr("cfh_disposition.google_property_runtime_bridge.resolve_read_only_google_access", lambda *a: (object(), "fictional-sheet"))
    monkeypatch.setattr("supabase.create_client", lambda *a: SimpleNamespace(storage=SimpleNamespace(from_=lambda name: Bucket())))
    monkeypatch.setattr("cfh_disposition.property_change_cache.RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(runtime, "load_baseline_source", load_baseline_source)
    secrets = {"SUPABASE_URL": "https://fictional.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fictional", "GOOGLE_SHEET_ID": "fictional-sheet"}
    runtime.read_property_changes(secrets, force=True)
    first = read_cache(cache_path(secrets))["inventory_observations"]
    # Source wording changes to its equivalent abbreviation on the second check.
    addresses[0] = "101 N Example St, Example City, IL 60000"
    runtime.read_property_changes(secrets, force=True)
    second = read_cache(cache_path(secrets))["inventory_observations"]
    assert calls.count("values:batchGet") == 2
    for p in properties:
        assert first[p["id"]]["marketing_status"] == second[p["id"]]["marketing_status"] == "yellow"
        assert first[p["id"]]["marketing_observed_since"] == second[p["id"]]["marketing_observed_since"]
        assert first[p["id"]]["marketing_observed_since"]
