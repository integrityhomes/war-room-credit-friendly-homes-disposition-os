"""Explicit local integration pytest suite; uses the existing Gordon checkout.

Run with GORDON_CHECKOUT set, python -B -m pytest scripts/check_gordon_handshake.py
and an isolated --basetemp. Not collected by the offline business simulator:
its process/file wall remains intact. No Gordon code is copied or modified.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from cfh_disposition.corepilot_gordon import INSPECTIONS, GordonConnection, GordonJob, existing_adapter
from cfh_disposition.corepilot_orchestrator import run_corepilot


@pytest.fixture
def connection(tmp_path):
    sys.dont_write_bytecode = True
    checkout = Path(os.environ["GORDON_CHECKOUT"]).resolve(strict=True)
    root = tmp_path / "fixture"
    root.mkdir()
    for name in set(INSPECTIONS.values()):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Fictional local inspection fixture.\n", encoding="utf-8")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    adapter = existing_adapter(checkout, root, tmp_path / "audit" / "jobs.jsonl")
    assert Path(sys.modules[type(adapter).__module__].__file__).resolve() == checkout / "app" / "local_adapter.py"
    yield GordonConnection(adapter)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


def identity():
    return GordonJob(idempotency_key=uuid4(), correlation_id=uuid4())


def request(**changes):
    value = {"job_type": "technical.inspect", "steps": [{"command": "read", "path": "pyproject.toml"}],
             "idempotency_key": str(uuid4()), "correlation_id": str(uuid4()), "timeout_seconds": 10.0}
    return value | changes


def test_real_corepilot_handshake_duplicate_restart_and_audit(connection):
    job = identity()
    first = run_corepilot("System diagnostics", {}, gordon=connection, gordon_job=job)
    response = first.gordon_outcome
    assert first.status == "completed", first
    assert response["accepted"] and response["job_id"] and response["error"] is None
    assert response["result"]["content_withheld"] and response["actions_attempted"] == [{"step": 1, "command": "read", "status": "completed"}]
    assert response["cost"] == {"api_calls": 0, "models": [], "cost_usd": 0.0}
    assert not response["approvals_required"]
    adapter = type(connection.adapter)(connection.adapter.root, connection.adapter.journal)
    with patch.object(adapter, "_execute", side_effect=AssertionError("Duplicate executed")) as execute:
        duplicate = run_corepilot("System diagnostics", {}, gordon=GordonConnection(adapter), gordon_job=job).gordon_outcome
        assert not duplicate["accepted"] and duplicate["error"]["code"] == "duplicate_job"
        assert duplicate["job_id"] == response["job_id"] and duplicate["actions_attempted"] == []
        execute.assert_not_called()
    rows = [json.loads(line) for line in adapter.journal.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["accepted", "action_started", "terminal", "duplicate"]
    assert all(row["correlation_id"] == str(job.correlation_id) and row["job_id"] == response["job_id"] for row in rows)
    assert response["audit"]["event_id"] == rows[2]["audit"]["event_id"]


@pytest.mark.parametrize("lane", list(INSPECTIONS))
def test_all_supported_inspections_real_worker(connection, lane):
    result = connection.inspect(lane, identity())
    assert result["accepted"] and result["status"] == "completed"


@pytest.mark.parametrize("kind", ["deploy", "paid_api", "spend_money", "credentials", "production", "external_communication", "publish_marketing"])
def test_existing_owner_gate_has_no_execution(connection, kind):
    with patch.object(connection.adapter, "_execute") as execute:
        result = connection.adapter.submit(request(job_type=kind))
        execute.assert_not_called()
    assert not result["accepted"] and result["status"] == "approval_required"
    assert result["approvals_required"][0]["owners"] == ["Shawn", "Sabrina"]
    assert not result["actions_attempted"]


@pytest.mark.parametrize("changes,code", [({"job_type": "unsupported"}, "unsupported_job"),
    ({"approved_by": "Shawn"}, "invalid_request"), ({"steps": [{"command": "run", "path": "pyproject.toml"}]}, "approval_required"),
    ({"steps": [{"command": "read", "path": "../secret"}]}, "path_rejected")])
def test_existing_unsupported_forged_and_arbitrary_requests_reject(connection, changes, code):
    with patch.object(connection.adapter, "_execute") as execute:
        result = connection.adapter.submit(request(**changes))
        execute.assert_not_called()
    assert not result["accepted"] and result["error"]["code"] == code and result["actions_attempted"] == []


def test_failure_and_timeout_reach_corepilot_cleanly(connection):
    for error, status, code in [(RuntimeError("fictional-private-error"), "failed", "execution_failed"), (TimeoutError(), "timed_out", "timeout")]:
        with patch.object(connection.adapter, "_execute", side_effect=error):
            result = run_corepilot("System diagnostics", {}, gordon=connection, gordon_job=identity())
        assert result.status == status and result.gordon_outcome["error"] == {"code": code}
        assert "fictional-private-error" not in str(result) + connection.adapter.journal.read_text()


def test_real_worker_deadline_kills_and_reports(connection):
    real = subprocess.run
    def sleeper(command, **kwargs):
        return real([command[0], "-I", "-B", "-c", "import time; time.sleep(5)"], **kwargs)
    with patch.object(subprocess, "run", side_effect=sleeper):
        result = connection.adapter.submit(request(timeout_seconds=0.05))
    assert result["status"] == "timed_out" and result["error"] == {"code": "timeout"}
    assert result["audit"]["durable"]


def test_missing_file_failure_and_conflicting_duplicate(connection):
    job = request(steps=[{"command": "read", "path": "missing.txt"}])
    failed = connection.adapter.submit(job)
    assert failed["status"] == "failed"
    with patch.object(connection.adapter, "_execute") as execute:
        conflict = connection.adapter.submit(job | {"steps": [{"command": "read", "path": "pyproject.toml"}]})
        execute.assert_not_called()
    assert conflict["error"]["code"] == "idempotency_conflict" and conflict["job_id"] == failed["job_id"]
