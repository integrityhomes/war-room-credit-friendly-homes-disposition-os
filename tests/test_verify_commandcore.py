from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_commandcore.py"
SPEC = importlib.util.spec_from_file_location("verify_commandcore", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
SOURCE = SCRIPT.read_text(encoding="utf-8")


def test_runner_targets_exact_commandcore_root_and_rejects_escapes() -> None:
    assert runner.ROOT == ROOT
    assert runner.approved_relative_path("tests/test_verify_commandcore.py")[1] == "tests/test_verify_commandcore.py"
    for value in ("../outside.py", "C:/outside.py", "/outside.py", "tests/*.py", ".git/config", ""):
        with pytest.raises(runner.VerificationError):
            runner.approved_relative_path(value)


def test_runner_reuses_read_only_network_disabled_codingbot_sandbox() -> None:
    assert '"--network", "none"' in SOURCE
    assert '"--read-only"' in SOURCE
    assert '"--cap-drop", "ALL"' in SOURCE
    assert '"no-new-privileges"' in SOURCE
    assert '"docker.sock"' in SOURCE
    assert "sandbox._container_arguments" in SOURCE
    assert "sandbox_execution.py" in SOURCE
    assert "_project_dependency_image(" not in SOURCE
    assert "networked image preparation is not allowed" in SOURCE


def test_runner_has_no_git_mutation_or_remote_operations() -> None:
    forbidden = (
        '"add"',
        '"commit"',
        '"push"',
        '"fetch"',
        '"pull"',
        '"merge"',
        '"rebase"',
        '"reset"',
        '"checkout"',
        "git add",
        "git commit",
    )
    for command in forbidden:
        assert command not in SOURCE
    assert '"status", "--short"' in SOURCE
    assert '"diff", "--check"' in SOURCE


def test_runner_has_no_live_credentials_or_external_calls() -> None:
    for forbidden in (
        "requests.",
        "urlopen",
        "httpx",
        "curl",
        "Invoke-WebRequest",
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENPHONE_API_KEY",
        "META_ACCESS_TOKEN",
        "OAuth",
    ):
        assert forbidden not in SOURCE
    assert '"HTTP_PROXY": ""' in SOURCE
    assert '"HTTPS_PROXY": ""' in SOURCE


def test_git_status_preserves_first_modified_path(monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "_checked",
        lambda arguments: " M scripts/verify_commandcore.py\n?? tests/new_test.py",
    )
    assert runner.git_status_paths() == [
        "scripts/verify_commandcore.py",
        "tests/new_test.py",
    ]


def test_owned_cleanup_requires_exact_path_and_matching_marker(tmp_path, monkeypatch) -> None:
    root = tmp_path
    parent = root / ".v"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "TEMP_PARENT", parent)
    monkeypatch.setattr(runner, "RUN_PREFIX", "r")
    monkeypatch.setattr(runner.secrets, "token_hex", lambda size: "owned")
    run_dir, run_id = runner.create_owned_temp()
    unrelated = root / "customer-file.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    runner.cleanup_owned_temp(run_dir, run_id)
    assert not run_dir.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve"

    forged = parent / "rforged"
    forged.mkdir(parents=True)
    (forged / runner.OWNERSHIP_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(runner.VerificationError, match="ownership marker"):
        runner.cleanup_owned_temp(forged, "forged")
    assert forged.exists()


def test_pytest_temp_is_workspace_local_owned_and_process_routed(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    parent = root / ".ccv"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "TEMP_PARENT", parent)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda size: "owned")
    run_dir, run_id = runner.create_owned_temp()
    stage, system_temp = runner.prepare_owned_test_temp(run_dir, run_id, "focused")
    assert stage.parent == run_dir
    assert system_temp.parent == run_dir

    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        captured["arguments"] = arguments
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, "passed", "")

    monkeypatch.setattr(runner, "approved_relative_path", lambda value: (root / value, value))
    monkeypatch.setattr(runner, "_python", lambda: sys.executable)
    monkeypatch.setattr(subprocess, "run", fake_run)
    runner.run_pytest(["tests/test_verify_commandcore.py"], stage, system_temp)
    environment = captured["env"]
    assert environment["TEMP"] == str(system_temp.resolve())
    assert environment["TMP"] == str(system_temp.resolve())
    assert environment["TMPDIR"] == str(system_temp.resolve())
    assert environment["PYTEST_DEBUG_TEMPROOT"] == str(stage.resolve())
    assert os.path.commonpath([environment["TEMP"], str(run_dir)]) == str(run_dir)
    assert "tmp_path_retention_policy=none" in captured["arguments"]
    if sys.platform == "win32":
        assert runner.WINDOWS_PYTEST_TEMP_WRAPPER in captured["arguments"]


def test_windows_pytest_wrapper_changes_only_restrictive_temp_mode() -> None:
    assert "safe_mode = 0o777 if mode == 0o700 else mode" in runner.WINDOWS_PYTEST_TEMP_WRAPPER
    assert "os.mkdir = inherited_acl_mkdir" in runner.WINDOWS_PYTEST_TEMP_WRAPPER


def test_temp_setup_rejects_forged_marker_and_preexisting_stage(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    parent = root / ".ccv"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "TEMP_PARENT", parent)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda size: "owned")
    run_dir, run_id = runner.create_owned_temp()
    (run_dir / runner.OWNERSHIP_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(runner.VerificationError, match="outside the current owned run"):
        runner.prepare_owned_test_temp(run_dir, run_id, "focused")

    (run_dir / runner.OWNERSHIP_FILE).write_text(
        '{"run_id": "owned", "root": "' + str(root).replace("\\", "\\\\") + '"}',
        encoding="utf-8",
    )
    (run_dir / "focused").mkdir()
    with pytest.raises(runner.VerificationError, match="not safely writable"):
        runner.prepare_owned_test_temp(run_dir, run_id, "focused")


def test_windows_temp_root_length_fails_closed(tmp_path, monkeypatch) -> None:
    root = tmp_path / ("r" * 190)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "TEMP_PARENT", root / ".ccv")
    monkeypatch.setattr(runner.os, "name", "nt")
    with pytest.raises(runner.VerificationError, match="too long"):
        runner.create_owned_temp()


def test_cleanup_permission_error_is_reported_fail_closed(tmp_path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    parent = root / ".ccv"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "TEMP_PARENT", parent)
    monkeypatch.setattr(runner, "MAX_WINDOWS_TEMP_ROOT_LENGTH", 1_000)
    run_dir, run_id = runner.create_owned_temp()
    monkeypatch.setattr(runner.shutil, "rmtree", lambda path: (_ for _ in ()).throw(PermissionError("denied")))
    with pytest.raises(runner.VerificationError, match="marker-owned"):
        runner.cleanup_owned_temp(run_dir, run_id)
    assert run_dir.exists()


def test_interrupted_run_still_cleans_owned_temp(tmp_path, monkeypatch) -> None:
    changed = "scripts/verify_commandcore.py"
    run_dir = tmp_path / "owned-run"
    run_dir.mkdir()
    cleaned: list[Path] = []
    monkeypatch.setattr(runner, "verify_repository", lambda: None)
    monkeypatch.setattr(runner, "git_status_paths", lambda: [changed])
    monkeypatch.setattr(runner, "approved_relative_path", lambda value, must_exist=True: (ROOT / value, value))
    monkeypatch.setattr(runner, "create_owned_temp", lambda: (run_dir, "owned"))
    monkeypatch.setattr(
        runner,
        "prepare_owned_test_temp",
        lambda root, run_id, stage: (root / stage, root / "tmp"),
    )
    monkeypatch.setattr(runner, "cleanup_owned_temp", lambda root, run_id: cleaned.append(root))
    monkeypatch.setattr(runner, "run_pytest", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        runner.verify(changed=[changed], focused=["tests/test_verify_commandcore.py"])
    assert cleaned == [run_dir]


def test_failure_stops_later_verification_and_preserves_unrelated_dirty_files(monkeypatch, tmp_path) -> None:
    changed = "scripts/verify_commandcore.py"
    unrelated = "notes/user-work.txt"
    called: list[str] = []
    monkeypatch.setattr(runner, "verify_repository", lambda: None)
    monkeypatch.setattr(runner, "git_status_paths", lambda: [changed, unrelated])
    monkeypatch.setattr(runner, "create_owned_temp", lambda: (tmp_path, "owned"))
    monkeypatch.setattr(runner, "cleanup_owned_temp", lambda *_: None)
    monkeypatch.setattr(runner, "approved_relative_path", lambda value, must_exist=True: (ROOT / value, value))

    def fail_focused(paths, basetemp, system_temp):
        called.append("focused")
        raise runner.VerificationError("focused failure")

    monkeypatch.setattr(runner, "prepare_owned_test_temp", lambda root, run_id, stage: (root / stage, root / "tmp"))
    monkeypatch.setattr(runner, "run_pytest", fail_focused)
    monkeypatch.setattr(runner, "run_ruff", lambda: called.append("ruff") or "passed")
    monkeypatch.setattr(runner, "run_trusted_docker", lambda paths: called.append("docker") or "passed")
    report = runner.verify(changed=[changed], focused=["tests/test_verify_commandcore.py"], full=True)
    assert report.status == "FAIL"
    assert report.failed_step == "focused tests"
    assert called == ["focused"]
    assert report.unrelated_dirty_files == [unrelated]


def test_pass_summary_reports_exact_changed_files(monkeypatch, tmp_path) -> None:
    changed = ["scripts/verify_commandcore.py", "tests/test_verify_commandcore.py"]
    monkeypatch.setattr(runner, "verify_repository", lambda: None)
    monkeypatch.setattr(runner, "git_status_paths", lambda: changed)
    monkeypatch.setattr(runner, "create_owned_temp", lambda: (tmp_path, "owned"))
    monkeypatch.setattr(runner, "cleanup_owned_temp", lambda *_: None)
    monkeypatch.setattr(runner, "approved_relative_path", lambda value, must_exist=True: (ROOT / value, value))
    monkeypatch.setattr(runner, "prepare_owned_test_temp", lambda root, run_id, stage: (root / stage, root / "tmp"))
    monkeypatch.setattr(runner, "run_pytest", lambda paths, basetemp, system_temp: "tests passed")
    monkeypatch.setattr(runner, "run_ruff", lambda: "ruff passed")
    monkeypatch.setattr(runner, "secret_and_diff_review", lambda paths: "secrets passed")
    monkeypatch.setattr(runner, "run_trusted_docker", lambda paths: "docker passed")
    report = runner.verify(changed=changed, focused=["tests/test_verify_commandcore.py"], regression=["tests/test_security.py"], full=True)
    assert report.status == "PASS"
    assert report.changed_files == changed
    assert report.unrelated_dirty_files == []
    assert report.cleanup_completed is True
    assert report.remote_git_operations == "NONE"
    assert report.external_service_spend == "$0"
    assert [step.name for step in report.steps] == [
        "focused tests",
        "regression tests",
        "full CommandCore suite",
        "repository Ruff",
        "secret and diff review",
        "trusted read-only Docker",
        "owned temporary cleanup",
        "final git status",
    ]


def test_secret_scanner_detects_likely_values(monkeypatch, tmp_path) -> None:
    fake = tmp_path / "unsafe.py"
    key_name = "access_" + "token"
    fake.write_text(f'{key_name}="abcdefghijklmnopqrstuvwxyz123456"', encoding="utf-8")
    monkeypatch.setattr(runner, "approved_relative_path", lambda value, must_exist=True: (fake, value))
    monkeypatch.setattr(runner, "_checked", lambda *args, **kwargs: "")
    with pytest.raises(runner.VerificationError, match="possible credential"):
        runner.secret_and_diff_review(["unsafe.py"])


def test_commands_use_argument_arrays_without_shell(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(arguments, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner._run(["git", "status"])
    assert captured["shell"] is False
    assert captured["check"] is False


def test_full_suite_uses_existing_commandcore_tests_directory() -> None:
    assert (ROOT / "tests").is_dir()
    assert "run_pytest([\"tests\"]" in SOURCE
