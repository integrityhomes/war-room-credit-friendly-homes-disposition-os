"""One fail-closed local verification entry point for approved CommandCore builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
TEMP_PARENT = ROOT / ".commandcore-verification"
BOT_DEV_ROOT = ROOT.parent / "bot_dev"
BOT_DEV_APP = BOT_DEV_ROOT / "app"
OWNERSHIP_FILE = ".commandcore-verification-owner.json"
RUN_PREFIX = "run-"
MAX_OUTPUT = 12_000
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|oauth[_ -]?secret|carrier[_ -]?pin)\s*[:=]\s*['\"]?(?!\[?redacted|example|test|fake|dummy)[^\s'\"]{8,}",
        re.IGNORECASE,
    ),
)
SECRET_PATH_PARTS = {".env", "secrets", "credentials", "tokens"}


class VerificationError(RuntimeError):
    """The approved verification sequence could not complete safely."""


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class VerificationReport:
    status: str = "FAIL"
    repository: str = str(ROOT)
    changed_files: list[str] = field(default_factory=list)
    unrelated_dirty_files: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    failed_step: str = ""
    cleanup_completed: bool = False
    worktree_clean: bool = False
    remote_git_operations: str = "NONE"
    external_service_spend: str = "$0"

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.steps.append(StepResult(name, passed, detail[-MAX_OUTPUT:]))
        if not passed and not self.failed_step:
            self.failed_step = name

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "steps": [asdict(step) for step in self.steps]}


def _inside_root(path: Path) -> bool:
    try:
        path.relative_to(ROOT)
    except ValueError:
        return False
    return True


def approved_relative_path(value: str, *, must_exist: bool = True) -> tuple[Path, str]:
    raw = str(value or "").strip().replace("\\", "/")
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw)
    if (
        not raw
        or "\x00" in raw
        or "\n" in raw
        or "\r" in raw
        or windows.is_absolute()
        or windows.drive
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
        or any(char in raw for char in "*?[")
        or raw.startswith(":")
        or ".git" in {part.casefold() for part in posix.parts}
    ):
        raise VerificationError(f"Unsafe project path: {value!r}")
    target = (ROOT / Path(*posix.parts)).resolve()
    if target == ROOT or not _inside_root(target):
        raise VerificationError(f"Path is outside CommandCore: {value!r}")
    if must_exist and not target.exists():
        raise VerificationError(f"Verification target does not exist: {raw}")
    return target, target.relative_to(ROOT).as_posix()


def _run(arguments: Sequence[str], *, cwd: Path = ROOT, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_OPTIONAL_LOCKS": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_PROXY": "*",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
        }
    )
    try:
        return subprocess.run(
            list(arguments),
            cwd=str(cwd),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VerificationError(f"Could not safely run {arguments[0]}: {exc}") from exc


def _checked(arguments: Sequence[str], *, cwd: Path = ROOT, timeout: int = 900) -> str:
    result = _run(arguments, cwd=cwd, timeout=timeout)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise VerificationError(output or f"{arguments[0]} exited {result.returncode}")
    return output


def verify_repository() -> None:
    actual = Path(_checked(["git", "rev-parse", "--show-toplevel"])).resolve()
    if os.path.normcase(str(actual)) != os.path.normcase(str(ROOT)):
        raise VerificationError("Git root does not match the authorized CommandCore workspace")
    if not (BOT_DEV_APP / "sandbox_execution.py").is_file():
        raise VerificationError("The installed CodingBot trusted sandbox runtime is unavailable")


def git_status_paths() -> list[str]:
    output = _checked(["git", "status", "--short", "--untracked-files=all"])
    paths: list[str] = []
    for line in output.splitlines():
        value = line[3:].strip()
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            paths.append(value.replace("\\", "/"))
    return sorted(set(paths))


def create_owned_temp() -> tuple[Path, str]:
    TEMP_PARENT.mkdir(exist_ok=True)
    run_id = secrets.token_hex(16)
    run_dir = (TEMP_PARENT / f"{RUN_PREFIX}{run_id}").resolve()
    if run_dir.parent != TEMP_PARENT.resolve() or not _inside_root(run_dir):
        raise VerificationError("Verification temporary path escaped its owned parent")
    run_dir.mkdir()
    (run_dir / OWNERSHIP_FILE).write_text(json.dumps({"run_id": run_id, "root": str(ROOT)}), encoding="utf-8")
    return run_dir, run_id


def cleanup_owned_temp(run_dir: Path, run_id: str) -> None:
    resolved = run_dir.resolve()
    marker = resolved / OWNERSHIP_FILE
    expected = TEMP_PARENT.resolve() / f"{RUN_PREFIX}{run_id}"
    if resolved != expected or resolved.parent != TEMP_PARENT.resolve() or not _inside_root(resolved):
        raise VerificationError("Refusing to clean an unowned verification path")
    try:
        ownership = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError("Refusing cleanup because the ownership marker is missing or invalid") from exc
    if ownership != {"run_id": run_id, "root": str(ROOT)}:
        raise VerificationError("Refusing cleanup because the ownership marker does not match")
    shutil.rmtree(resolved)
    if TEMP_PARENT.exists() and not any(TEMP_PARENT.iterdir()):
        TEMP_PARENT.rmdir()


def _python() -> str:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    if not candidate.is_file():
        candidate = ROOT / ".venv" / "bin" / "python"
    if not candidate.is_file():
        raise VerificationError("CommandCore virtual-environment Python is unavailable")
    return str(candidate)


def run_pytest(paths: Sequence[str], basetemp: Path) -> str:
    if not paths:
        raise VerificationError("At least one test target is required")
    approved = [approved_relative_path(path)[1] for path in paths]
    return _checked([_python(), "-m", "pytest", "-p", "no:cacheprovider", "--basetemp", str(basetemp), *approved])


def run_ruff() -> str:
    return _checked([_python(), "-m", "ruff", "check", "."])


def _dependency_image_name(sandbox: object) -> str:
    requirements = ROOT / "requirements.txt"
    if not requirements.is_file():
        return str(sandbox.TRUSTED_SANDBOX_IMAGE)
    filtered = sandbox._filtered_requirements(requirements)  # type: ignore[attr-defined]
    if not filtered.strip():
        return str(sandbox.TRUSTED_SANDBOX_IMAGE)
    digest = hashlib.sha256()
    digest.update(b"coding-bot-dependency-image-v2\0")
    digest.update(str(sandbox.TRUSTED_SANDBOX_IMAGE).encode())
    digest.update(b"\0")
    digest.update(requirements.read_bytes())
    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        digest.update(b"\0pyproject.toml\0")
        digest.update(pyproject.read_bytes())
    return "coding-bot-execution-sandbox-deps:" + digest.hexdigest()[:16]


def run_trusted_docker(paths: Sequence[str]) -> str:
    approved = [approved_relative_path(path)[1] for path in paths]
    if not approved:
        raise VerificationError("Trusted Docker verification requires focused tests")
    sys.path.insert(0, str(BOT_DEV_APP))
    try:
        import sandbox_execution as sandbox
    finally:
        sys.path.pop(0)
    sandbox.set_project_anchor(ROOT)
    image = _dependency_image_name(sandbox)
    inspected = sandbox._docker(["image", "inspect", image])
    if inspected.returncode != 0:
        raise VerificationError(f"Trusted cached Docker image is missing: {image}; networked image preparation is not allowed")
    command = ["python", "-m", "pytest", "-p", "no:cacheprovider", *[f"{sandbox.CONTAINER_PROJECT_ROOT}/{path}" for path in approved]]
    arguments = sandbox._container_arguments(command, image=image)
    required = {"--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"}
    if not required.issubset(set(arguments)) or any("docker.sock" in item.casefold() for item in arguments):
        raise VerificationError("Trusted Docker arguments failed the CommandCore safety contract")
    result = sandbox._docker(arguments)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        raise VerificationError(output or "Trusted Docker verification failed")
    return output


def secret_and_diff_review(changed_files: Sequence[str]) -> str:
    findings: list[str] = []
    for value in changed_files:
        path, relative = approved_relative_path(value)
        lowered = {part.casefold() for part in PurePosixPath(relative).parts}
        if lowered & SECRET_PATH_PARTS or PurePosixPath(relative).name.casefold().startswith(".env"):
            findings.append(f"secret-sensitive path: {relative}")
            continue
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            for pattern in SECRET_PATTERNS:
                if pattern.search(content):
                    findings.append(f"possible credential value: {relative}")
                    break
    diff = _checked(["git", "diff", "--check", "--", *changed_files])
    if findings:
        raise VerificationError("; ".join(findings))
    return diff or f"No credential values or whitespace errors found in {len(changed_files)} scoped file(s)."


def verify(
    *,
    changed: Sequence[str],
    focused: Sequence[str],
    regression: Sequence[str] = (),
    full: bool = False,
) -> VerificationReport:
    report = VerificationReport()
    run_dir: Path | None = None
    run_id = ""
    try:
        verify_repository()
        changed_files = [approved_relative_path(path)[1] for path in changed]
        if not changed_files or len(set(changed_files)) != len(changed_files):
            raise VerificationError("Changed-file list must be non-empty and contain no duplicates")
        focused_tests = [approved_relative_path(path)[1] for path in focused]
        regression_tests = [approved_relative_path(path)[1] for path in regression]
        initial_dirty = git_status_paths()
        missing = sorted(set(changed_files) - set(initial_dirty))
        if missing:
            raise VerificationError("Declared changed files are not dirty: " + ", ".join(missing))
        report.changed_files = changed_files
        report.unrelated_dirty_files = sorted(set(initial_dirty) - set(changed_files))
        run_dir, run_id = create_owned_temp()

        for name, operation in (
            ("focused tests", lambda: run_pytest(focused_tests, run_dir / "focused")),
            ("regression tests", lambda: run_pytest(regression_tests, run_dir / "regression") if regression_tests else "Not requested"),
            ("full CommandCore suite", lambda: run_pytest(["tests"], run_dir / "full") if full else "Not requested"),
            ("repository Ruff", run_ruff),
            ("secret and diff review", lambda: secret_and_diff_review(changed_files)),
            ("trusted read-only Docker", lambda: run_trusted_docker(focused_tests)),
        ):
            try:
                detail = operation()
            except VerificationError as exc:
                report.add(name, False, str(exc))
                break
            report.add(name, True, detail or "Passed")
    except VerificationError as exc:
        report.add("preflight", False, str(exc))
    finally:
        if run_dir is not None:
            try:
                cleanup_owned_temp(run_dir, run_id)
                report.cleanup_completed = True
                report.add("owned temporary cleanup", True, "Removed only the marker-verified directory created by this run.")
            except VerificationError as exc:
                report.add("owned temporary cleanup", False, str(exc))
        try:
            final_dirty = git_status_paths()
            report.worktree_clean = not final_dirty
            if report.changed_files:
                report.unrelated_dirty_files = sorted(set(final_dirty) - set(report.changed_files))
            report.add("final git status", True, f"Dirty files: {final_dirty or 'none'}")
        except VerificationError as exc:
            report.add("final git status", False, str(exc))
    report.status = "PASS" if report.steps and all(step.passed for step in report.steps) else "FAIL"
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run one trusted local CommandCore verification sequence.")
    result.add_argument("--changed", action="append", required=True, help="Exact approved changed file; repeat for each file.")
    result.add_argument("--focused", action="append", required=True, help="Exact focused pytest target; repeat as needed.")
    result.add_argument("--regression", action="append", default=[], help="Exact regression pytest target; repeat as needed.")
    result.add_argument("--full", action="store_true", help="Run the complete CommandCore test suite.")
    return result


def main(arguments: Sequence[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    report = verify(changed=options.changed, focused=options.focused, regression=options.regression, full=options.full)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
