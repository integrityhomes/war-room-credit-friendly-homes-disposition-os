"""Offline simulator launcher and results inventory; no production-mode option."""

import ast
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / ".commandcore-runtime" / "business-simulator"
ACTIVE_SCENARIO = "startup"


def module_inventory():
    paths = [*ROOT.joinpath("src/cfh_disposition").rglob("*.py"), *ROOT.joinpath("pages").glob("*.py"), ROOT / "app.py"]
    result = []
    for path in sorted(paths):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        result.append({"module": path.relative_to(ROOT).as_posix(),
                       "functions": sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree))})
    return result


def launch(test_paths=None, *, probe=None):
    """Start a credential-free subprocess; its irreversible wall precedes pytest."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="run-", dir=RESULTS))
    environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "COMSPEC") if key in os.environ}
    environment.update({"TEMP": str(folder), "TMP": str(folder), "HOME": str(folder), "USERPROFILE": str(folder),
                        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false"})
    selection = test_paths or ["tests"]
    # No arbitrary command, executable, credentials, mode, or path can be supplied.
    for name in selection:
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT / "tests") or not path.exists():
            raise ValueError("Only repository tests may run in the simulator")
    (folder / "selection.json").write_text(json.dumps(selection))
    (folder / "inventory.json").write_text(json.dumps(module_inventory()))
    if probe:
        if probe not in {"network", "production-file", "production-adapter"}:
            raise ValueError("Unknown isolation probe")
        (folder / "probe.json").write_text(json.dumps(probe))
    subprocess.Popen([sys.executable, "-B", str(ROOT / "scripts/run_business_simulator.py"), "--worker", str(folder)],
                     cwd=folder, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return folder


def install_wall(folder):
    """Irreversible audit hook: abort the whole child on external I/O attempts.

    This boundary assumes trusted repository Python, not hostile native code.
    It is never installed in the production Streamlit process.
    """
    folder = Path(folder).resolve()
    allowed_reads = (ROOT, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(), folder)

    def fail(event, reason=""):
        # Record event class only, never a URL, path, token, payload or lockbox.
        (folder / "safety-failure.json").write_text(json.dumps({"status": "FAIL", "event": event,
            "production_access_attempted": True, "operation_blocked": True, "reason": reason, "scenario": ACTIVE_SCENARIO,
            "when": datetime.now(UTC).isoformat()}))
        os._exit(90)

    def path_allowed(value, write=False):
        if isinstance(value, int) or value is None:
            return True
        if os.fsdecode(value).casefold() in {os.devnull.casefold(), r"\\.\nul"}:
            return True  # pytest's discard-only capture device, never a data file.
        try:
            path = Path(os.fsdecode(value)).resolve()
        except (TypeError, ValueError):
            return False
        if path.is_relative_to(folder):
            return True
        if write:
            return False
        if path.is_relative_to(ROOT / ".commandcore-runtime") or ".streamlit" in path.parts or ".git" in path.parts:
            return False
        if path.name in {".env", "secrets.toml"} or (path.suffix == ".json" and any(w in path.name.casefold() for w in ("credential", "service-account"))):
            return False
        if not path.exists():
            return True  # Harmless optional-library config probes still raise FileNotFoundError.
        return any(path.is_relative_to(base) for base in allowed_reads)

    def audit(event, args):
        if event in {"os.symlink", "os.link"}:
            destination = Path(os.fsdecode(args[1])).resolve()
            source = Path(os.fsdecode(args[0]))
            target = source.resolve() if source.is_absolute() else (destination.parent / source).resolve()
            if destination.is_relative_to(folder) and target.is_relative_to(folder):
                return  # pytest's internal run-directory links cannot reach production.
        if event in {"socket.bind", "socket.connect"}:
            frame = sys._getframe(1)
            # Windows asyncio uses a stdlib loopback socketpair as its wakeup
            # pipe. Permit only that pipe, never arbitrary loopback services.
            if frame.f_code.co_name == "_fallback_socketpair" and Path(frame.f_code.co_filename).resolve() == Path(sys.base_prefix) / "Lib/socket.py":
                address = args[1]
                listener = frame.f_locals.get("lsock")
                if address[0] in {"127.0.0.1", "::1"} and (event == "socket.bind" and address[1] == 0
                    or event == "socket.connect" and listener and address[:2] == listener.getsockname()[:2]):
                    return
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind", "socket.sendto",
                     "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.startfile", "os.symlink", "os.link", "commandcore.production_action"}:
            fail(event, sys._getframe(1).f_code.co_filename + ":" + sys._getframe(1).f_code.co_name)
        if event == "open":
            name, mode, flags = args
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
            if not path_allowed(name, write):
                fail("file-write" if write else "protected-file-read", "Protected file name: " + Path(os.fsdecode(name)).name + "; caller: " + sys._getframe(1).f_code.co_filename)
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate", "os.utime"} and not path_allowed(args[0], True):
            fail("filesystem-mutation")
        if event in {"os.rename", "os.replace"} and not all(path_allowed(p, True) for p in args[:2]):
            fail("filesystem-move")

    sys.addaudithook(audit)


def worker(folder):
    import socket
    import threading

    folder = Path(folder).resolve()
    selection = json.loads((folder / "selection.json").read_text())
    inventory = json.loads((folder / "inventory.json").read_text())
    sys.dont_write_bytecode = True
    socket.has_ipv6 = False  # Offline adapter: avoid urllib3's real bind capability probe.
    install_wall(folder)
    if (folder / "probe.json").exists():
        probe = json.loads((folder / "probe.json").read_text())
        if probe == "network":
            sys.audit("socket.connect", None, ("192.0.2.1", 443))
        elif probe == "production-file":
            (ROOT / "SIMULATION-MUST-NOT-CREATE").write_text("forbidden")
        else:
            sys.audit("commandcore.production_action", "synthetic denied adapter")
        raise AssertionError("Safety wall failed to stop the probe")
    import pytest
    import streamlit.config

    streamlit.config.set_option("secrets.files", [])
    streamlit.config.set_option("browser.gatherUsageStats", False)
    os.chdir(ROOT)  # Existing source-inspection tests use repo-relative paths; writes stay jailed.
    outcomes, touched = [], set()
    modules = {str((ROOT / item["module"]).resolve()): item["module"] for item in inventory}
    current = [""]
    coverage = {}

    def profile(frame, event, arg):
        if event == "call" and current[0]:
            name = modules.get(frame.f_code.co_filename)
            if name and (frame.f_code.co_name != "<module>" or name.startswith("pages/")):
                touched.add(name)

    class Plugin:
        def pytest_collection_modifyitems(self, items):
            for item in items:
                if item.name == "test_cross_process_lock_prevents_overlapping_checks":
                    item.add_marker(pytest.mark.skip(reason="Simulator forbids unguarded child processes; cross-process lock coverage requires a guarded child adapter."))

        def pytest_collectreport(self, report):
            if report.failed:
                outcomes.append({"scenario": report.nodeid, "status": "FAIL", "expected": "Scenario collection succeeds",
                                 "actual": "Test collection failed; inspect dependencies or fixture setup", "subsystem": [],
                                 "next_step": "Fix harness setup; do not infer business coverage"})

        def pytest_runtest_logstart(self, nodeid, location):
            global ACTIVE_SCENARIO
            ACTIVE_SCENARIO = nodeid
            current[0] = nodeid
            touched.clear()

        def pytest_runtest_logreport(self, report):
            if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
                status = {"passed": "PASS", "skipped": "WARNING", "failed": "FAIL"}[report.outcome]
                actual = {"PASS": "Expected assertions satisfied", "WARNING": "Scenario skipped / expected limitation",
                          "FAIL": "Existing behavior failed scenario assertions; review before production use"}[status]
                if status == "WARNING" and isinstance(report.longrepr, tuple):
                    actual = str(report.longrepr[2])[:800]
                if status == "WARNING" and getattr(report, "wasxfail", None):
                    actual = "Known workflow gap: " + str(report.wasxfail)[:700]
                if status == "FAIL" and hasattr(report.longrepr, "reprcrash"):
                    message = report.longrepr.reprcrash.message
                    protected = any(word in message.casefold() for word in ("lockbox", "secret", "token", "password", "access"))
                    actual = "Protected-value assertion failed; values withheld" if protected else message[:800]
                outcomes.append({"scenario": report.nodeid, "status": status, "expected": "Existing regression assertions and safety invariants",
                                 "actual": actual, "subsystem": sorted(touched),
                                 "next_step": "None" if status == "PASS" else "Review this scenario; do not silently change business rules"})
                for name in touched:
                    coverage.setdefault(name, []).append({"scenario": report.nodeid, "status": status})
                (folder / "progress.json").write_text(json.dumps({"scenarios": len(outcomes)}))
                (folder / "partial-results.json").write_text(json.dumps(outcomes))

    sys.setprofile(profile)
    threading.setprofile(profile)
    code = pytest.main([*[str(ROOT / name) for name in selection], "-q", "-p", "no:cacheprovider", "--tb=no",
                        "--basetemp", str(folder / "pytest"), "-o", "pythonpath=" + str(ROOT / "src")], plugins=[Plugin()])
    sys.setprofile(None)
    threading.setprofile(None)
    for item in inventory:
        item["scenarios"] = coverage.get(item["module"], [])
        item["status"] = ("FAIL" if any(s["status"] == "FAIL" for s in item["scenarios"]) else
                          "WARNING" if not item["scenarios"] or any(s["status"] == "WARNING" for s in item["scenarios"]) else "PASS")
        item["coverage"] = "Executed during scenarios (not exhaustive branch coverage)" if item["scenarios"] else "Not exercised in this run"
    result = {"finished_at": datetime.now(UTC).isoformat(), "exit_code": int(code), "modules_inventoried": len(inventory),
              "modules_exercised": sum(bool(i["scenarios"]) for i in inventory), "scenarios_run": len(outcomes),
              "counts": {status: sum(o["status"] == status for o in outcomes) for status in ("PASS", "WARNING", "FAIL")},
              "production_access_attempted": False, "results": outcomes, "coverage": inventory}
    (folder / "results.json").write_text(json.dumps(result, indent=2))


def read_result(folder):
    folder = Path(folder).resolve()
    if not folder.is_relative_to(RESULTS):
        raise ValueError("Invalid simulator results location")
    for name in ("safety-failure.json", "results.json", "progress.json"):
        if (folder / name).exists():
            return json.loads((folder / name).read_text())
    return {"status": "STARTING"}
