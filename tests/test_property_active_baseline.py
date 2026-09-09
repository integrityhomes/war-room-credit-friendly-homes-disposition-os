import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_property_baseline import source_rows

from cfh_disposition.property_active_baseline import import_first_active_baseline
from cfh_disposition.property_baseline import build_baseline_plan


@pytest.fixture
def plan():
    return build_baseline_plan(source_rows(29, 126, 300), [], source_reference_hash="fictional-sheet")


class CanonicalBucket:
    def __init__(self):
        self.records = {}
        self.writes = []
        self.fail_at = None

    def list(self, entity, options):
        return [{"name": path.split("/")[1]} for path in self.records if path.startswith(entity + "/")]

    def download(self, path):
        return self.records[path]

    def upload(self, path, payload, *, file_options):
        assert file_options == {"content-type": "application/json", "upsert": "false"}
        assert path.startswith("properties/")
        if path in self.records or len(self.writes) == self.fail_at:
            raise RuntimeError("Create failed")
        self.records[path] = payload
        self.writes.append(path)


def client(bucket):
    def get_bucket(name):
        assert name == "commandcore-crm-core"
        return bucket
    return SimpleNamespace(storage=SimpleNamespace(from_=get_bucket))


def test_only_active_canonical_records_created_metadata_preserved_and_replay_stops(plan):
    bucket = CanonicalBucket()
    result = import_first_active_baseline(client(bucket), plan, approved_snapshot=plan.snapshot_hash)
    assert result["created"] == result["active"] == 29
    assert all(result[key] == 0 for key in ("sold_imported", "review_imported", "deals_created", "deletions", "google_writes", "duplicate_records_created"))
    expected = {item.record["id"]: item.record for item in plan.properties if item.record["availability"] == "Available"}
    for payload in bucket.records.values():
        record = json.loads(payload)
        assert record["availability"] == "Available"
        for key, value in expected[record["id"]].items():
            assert record[key] == value
    with pytest.raises(ValueError, match="not empty"):
        import_first_active_baseline(client(bucket), plan, approved_snapshot=plan.snapshot_hash)
    assert len(bucket.writes) == 29


@pytest.mark.parametrize("fault", ["approval", "errors", "count", "duplicate", "sold_tab", "missing_metadata"])
def test_all_preconditions_checked_before_any_write(plan, fault):
    approval = plan.snapshot_hash
    if fault == "approval":
        approval = "not-approved"
    elif fault == "errors":
        plan = replace(plan, errors=("Source failure",))
    elif fault == "count":
        plan = replace(plan, skipped_review=299)
    elif fault == "duplicate":
        plan = replace(plan, properties=(plan.properties[0], plan.properties[0], *plan.properties[2:]))
    else:
        record = plan.properties[0].record
        if fault == "sold_tab":
            record["sync_metadata"]["source_tab"] = "SOLD"
        else:
            record["sync_metadata"].pop("source_row_hash")
        item = replace(plan.properties[0], record_json=json.dumps(record))
        plan = replace(plan, properties=(item, *plan.properties[1:]))
    bucket = CanonicalBucket()
    with pytest.raises((ValueError, PermissionError)):
        import_first_active_baseline(client(bucket), plan, approved_snapshot=approval)
    assert bucket.writes == []


def test_partial_failure_never_updates_deletes_or_retries(plan):
    bucket = CanonicalBucket()
    bucket.fail_at = 2
    with pytest.raises(RuntimeError, match="Create failed"):
        import_first_active_baseline(client(bucket), plan, approved_snapshot=plan.snapshot_hash)
    assert len(bucket.records) == 2
    with pytest.raises(ValueError, match="not empty"):
        import_first_active_baseline(client(bucket), plan, approved_snapshot=plan.snapshot_hash)
    assert len(bucket.writes) == 2
