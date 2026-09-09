import json

import pytest
from test_property_active_baseline import CanonicalBucket, client
from test_property_baseline import source_rows

from cfh_disposition.property_baseline import build_baseline_plan
from cfh_disposition.property_historical_baseline import import_second_historical_baseline


@pytest.fixture
def baseline():
    rows = source_rows(29, 126, 300)
    plan = build_baseline_plan(rows, [], source_reference_hash="fictional-source")
    bucket = CanonicalBucket()
    for item in plan.properties:
        record = item.record
        if record["availability"] == "Available":
            record.update(created_at="original-date", updated_at="original-date", archived=False)
            bucket.records[f"properties/{record['id']}.json"] = json.dumps(record).encode()
    return rows, plan, bucket


def run_import(rows, plan, bucket):
    return import_second_historical_baseline(client(bucket), rows, source_reference_hash="fictional-source", approved_snapshot=plan.snapshot_hash)


def test_historical_only_active_bytes_unchanged_and_replay_blocked(baseline):
    rows, plan, bucket = baseline
    before = dict(bucket.records)
    result = run_import(rows, plan, bucket)
    assert result["historical_created"] == 126
    assert result["existing_active_skipped"] == 29
    assert all(result[key] == 0 for key in ("active_altered", "review_imported", "deals_created", "closing_dates_created", "deletions", "google_writes", "preview_new"))
    assert all(bucket.records[path] == payload for path, payload in before.items())
    assert len(bucket.writes) == 126
    for path in bucket.writes:
        record = json.loads(bucket.records[path])
        assert record["availability"] == "Sold / Unavailable"
        assert record["sync_metadata"]["closing_verified"] is False
        assert record["sync_metadata"]["classification_basis"] == "source worksheet membership"
        assert record["links"] == {}
        assert not any(field in record for field in ("closing_date", "closed_at", "stage", "deal_id"))
    with pytest.raises(ValueError):
        run_import(rows, plan, bucket)
    assert len(bucket.writes) == 126


@pytest.mark.parametrize("fault", ["approval", "source_count", "active_change", "active_missing", "existing_historical", "duplicate_source"])
def test_preflight_failures_make_zero_writes(baseline, fault):
    rows, plan, bucket = baseline
    if fault == "approval":
        from dataclasses import replace
        plan = replace(plan, snapshot_hash="wrong")
    elif fault == "source_count":
        rows = rows[:-1]
    elif fault == "duplicate_source":
        rows = (*rows, rows[-1])
    elif fault == "active_missing":
        bucket.records.pop(next(iter(bucket.records)))
    else:
        path = next(iter(bucket.records))
        record = json.loads(bucket.records[path])
        record["availability" if fault == "existing_historical" else "asking_or_sale_price"] = "Sold / Unavailable" if fault == "existing_historical" else "999999"
        bucket.records[path] = json.dumps(record).encode()
    before = dict(bucket.records)
    with pytest.raises((ValueError, PermissionError)):
        run_import(rows, plan, bucket)
    assert not bucket.writes and bucket.records == before


def test_partial_failure_stops_and_preserves_all_active_records(baseline):
    rows, plan, bucket = baseline
    before = dict(bucket.records)
    bucket.fail_at = 2
    with pytest.raises(RuntimeError):
        run_import(rows, plan, bucket)
    assert len(bucket.writes) == 2
    assert all(bucket.records[path] == payload for path, payload in before.items())
    with pytest.raises(ValueError):
        run_import(rows, plan, bucket)
    assert len(bucket.writes) == 2
