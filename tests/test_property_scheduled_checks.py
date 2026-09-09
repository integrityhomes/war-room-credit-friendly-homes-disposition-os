import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_property_change_runtime import reader as source_reader

from cfh_disposition import property_change_runtime as runtime
from cfh_disposition.property_change_cache import cache_path, exclusive_check, read_cache

SECRETS = {"SUPABASE_URL": "fictional", "GOOGLE_SHEET_ID": "fictional-sheet"}


@pytest.fixture
def reader(monkeypatch, tmp_path):
    return source_reader.__wrapped__(monkeypatch, tmp_path)


def test_restart_deduplication_and_cached_reads_need_no_provider_calls(reader):
    calls, fail = reader
    first = runtime.read_property_changes(SECRETS, force=True)
    assert len(first.new_events) == 1
    importlib.reload(runtime)
    # Reapply the fixture's provider boundary after module reload.
    # Cached results must work even if every provider is unavailable.
    fail[0] = True
    cached = runtime.read_property_changes(SECRETS)
    assert cached == first and len(calls) == 2


def test_cross_process_lock_prevents_overlapping_checks(reader):
    path = cache_path(SECRETS)
    code = ("from pathlib import Path; from cfh_disposition.property_change_cache import exclusive_check; import sys\n"
            "try:\n with exclusive_check(Path(sys.argv[1])): pass\nexcept OSError:\n sys.exit(7)")
    with exclusive_check(path):
        result = subprocess.run([sys.executable, "-B", "-c", code, str(path)], capture_output=True)
    assert result.returncode == 7
    with exclusive_check(path):
        pass


def test_failed_run_keeps_evidence_and_checkpoint_and_never_stores_provider_details(reader):
    _, fail = reader
    runtime.read_property_changes(SECRETS, force=True)
    path = cache_path(SECRETS)
    before = read_cache(path)["result"]
    fail[0] = True
    with pytest.raises(RuntimeError):
        runtime.read_property_changes(SECRETS, force=True)
    after = read_cache(path)
    assert after["result"] == before and after["error"]
    assert "PRIVATE PROVIDER DETAIL" not in path.read_text()


def test_atomic_save_failure_retains_previous_checkpoint(reader, monkeypatch):
    from cfh_disposition.property_change_cache import save_cache
    path = cache_path(SECRETS)
    save_cache(path, {"version": 1, "test": "original"})
    def fail_replace(*args):
        raise OSError("Test interruption")
    monkeypatch.setattr("cfh_disposition.property_change_cache.os.replace", fail_replace)
    with pytest.raises(OSError):
        save_cache(path, {"version": 1, "test": "new"})
    assert json.loads(path.read_text())["test"] == "original"


def test_task_preparation_is_opt_in_limited_and_uses_existing_runtime():
    source = (Path(__file__).resolve().parents[1] / "scripts/register_property_check_task.ps1").read_text()
    assert "if (!$Activate)" in source
    assert "-LogonType Interactive -RunLevel Limited" in source
    assert "New-TimeSpan -Hours 2" in source and "-MultipleInstances IgnoreNew" in source
    assert "pythonw.exe" in source and "--scheduled" in source
    assert "-Password" not in source and "-Force" not in source
