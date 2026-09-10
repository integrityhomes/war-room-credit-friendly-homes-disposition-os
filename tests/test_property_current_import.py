import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_business_simulator_scenarios import synthetic_rows

from cfh_disposition.corepilot_inventory import inventory_items, observe_inventory, stale_checkpoint
from cfh_disposition.property_change_cache import exclusive_check
from cfh_disposition.property_current_import import execute_current_import, prepare_current_import


class CanonicalBucket:
    def __init__(self):
        self.records = {}
        self.uploads = 0
        self.fail_at = None

    def list(self, entity, options):
        return [{"name": key.split("/")[1]} for key in sorted(self.records) if key.startswith(entity + "/")][options["offset"]:options["offset"] + options["limit"]]

    def download(self, path):
        return self.records[path]

    def upload(self, path, payload, *, file_options):
        assert path.startswith("properties/") and file_options["upsert"] == "false"
        if self.fail_at == self.uploads:
            raise TimeoutError("Injected isolated failure")
        if path in self.records:
            raise FileExistsError("Atomic create-only conflict")
        self.records[path] = payload
        self.uploads += 1

    def client(self):
        def bucket(name):
            assert name == "commandcore-crm-core"
            return self
        return SimpleNamespace(storage=SimpleNamespace(from_=bucket))


def execute(bucket, rows, tmp_path, snapshot=None):
    plan = prepare_current_import(rows, source_reference_hash="synthetic-source")
    return execute_current_import(bucket.client(), rows, source_reference_hash="synthetic-source",
                                  approved_snapshot=snapshot or plan.snapshot_hash, lock_path=tmp_path / "source.json")


def test_real_current_executor_creates_29_once_and_ages_only_25(tmp_path):
    rows = synthetic_rows()
    bucket = CanonicalBucket()
    result = execute(bucket, rows, tmp_path)
    assert (result["created"], result["yellow"], result["white"]) == (29, 25, 4)
    before = copy.deepcopy(bucket.records)
    repeat = execute(bucket, rows, tmp_path)
    assert repeat["created"] == 0 and repeat["duplicates_prevented"] == 29 and bucket.records == before
    records = [json.loads(value) for value in bucket.records.values()]
    assert "SYNTHETIC-ACCESS" not in json.dumps(records)
    assert all("closed_at" not in p and p["links"] == {} for p in records)
    assert any(p["sync_metadata"]["historical_occurrences"] for p in records)
    assert sum(p["square_feet"] is None for p in records) == 12
    assert all(p["asking_or_sale_price"] == ("109000" if p["seller_entity"] == "Fictional Owner A" else "89000") for p in records)
    obs = observe_inventory(rows, records, checked_at="2035-01-01T00:00:00+00:00")
    from datetime import date, timedelta
    for day, count in ((0, 0), (9, 0), (10, 25), (14, 25), (21, 25)):
        obs = observe_inventory(rows, records, obs, checked_at=f"2035-01-{day+1:02d}T02:00:00+00:00")
        items = inventory_items(records, obs, today=date(2035, 1, 1) + timedelta(days=day))
        assert sum(p["marketing_status"] == "yellow" for p in items) == 25
        assert len(stale_checkpoint(records, obs, today=date(2035, 1, 1) + timedelta(days=day))["attention"]) == count
        assert all(not value["marketing_observed_since"] for value in obs.values() if value["marketing_status"] == "white")
    assert all(obs[p["id"]]["marketing_observed_since"] == "2035-01-01T00:00:00+00:00" for p in records if p["sync_metadata"]["marketing_status"] == "yellow")


def test_executor_rejects_changed_approval_and_duplicate_identity(tmp_path):
    rows = synthetic_rows()
    bucket = CanonicalBucket()
    with pytest.raises(PermissionError):
        execute(bucket, rows, tmp_path, "wrong")
    with pytest.raises(ValueError):
        execute(bucket, [*rows, replace(rows[0], row=999)], tmp_path)
    assert not bucket.records


def test_executor_partial_failure_stops_and_separate_retry_only_creates_missing(tmp_path):
    rows = synthetic_rows()
    bucket = CanonicalBucket()
    bucket.fail_at = 3
    with pytest.raises(TimeoutError):
        execute(bucket, rows, tmp_path)
    assert len(bucket.records) == 3
    existing = copy.deepcopy(bucket.records)
    bucket.fail_at = None
    result = execute(bucket, rows, tmp_path)
    assert result["created"] == 26 and result["duplicates_prevented"] == 3
    assert all(bucket.records[k] == v for k, v in existing.items())


def test_executor_lock_contention_stops_before_any_canonical_io(tmp_path):
    bucket = CanonicalBucket()
    with exclusive_check(tmp_path / "source.json"):
        with pytest.raises(OSError):
            execute(bucket, synthetic_rows(), tmp_path)
    assert not bucket.records


def test_imported_records_are_visible_through_real_corepilot_lookup(tmp_path):
    from cfh_disposition.corepilot_orchestrator import run_corepilot
    bucket = CanonicalBucket()
    execute(bucket, synthetic_rows(), tmp_path)
    records = [json.loads(value) for value in bucket.records.values()]
    target = records[0]
    answer = run_corepilot("Find " + target["address"], {"properties": records})
    assert not answer.clarification and dict(answer.context)["property_id"] == target["id"]
    assert answer.records_written == answer.external_actions_started == 0


def test_executor_access_redaction_never_corrupts_numeric_facts_or_identity():
    rows = synthetic_rows()
    changed = [replace(r, fields={**r.fields, "lockbox_code": "1000", "notes": "Lockbox 1000"}) for r in rows]
    plan = prepare_current_import(changed, source_reference_hash="synthetic-source")
    assert any(r["address"] == "1000 Simulation Lane" for r in plan.records)
    assert all(r["notes"] is None for r in plan.records)
    assert all(r["asking_or_sale_price"] in {"89000", "109000"} for r in plan.records)
    original = prepare_current_import(rows, source_reference_hash="synthetic-source")
    assert {r["id"] for r in original.records} == {r["id"] for r in plan.records}


def test_second_simultaneous_import_worker_is_rejected(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()

    class HeldBucket(CanonicalBucket):
        def upload(self, *args, **kwargs):
            if self.uploads == 0:
                entered.set()
                assert release.wait(10), "Test worker was not released"
            return super().upload(*args, **kwargs)

    bucket = HeldBucket()
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(execute, bucket, synthetic_rows(), tmp_path)
        try:
            assert entered.wait(10)
            second = workers.submit(execute, bucket, synthetic_rows(), tmp_path)
            with pytest.raises(OSError):
                second.result(timeout=10)
        finally:
            release.set()
        assert first.result(timeout=10)["created"] == 29
    assert bucket.uploads == len(bucket.records) == 29
