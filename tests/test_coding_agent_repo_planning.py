from __future__ import annotations

from pathlib import Path

from cfh_disposition.coding_agent import build_ticket
from cfh_disposition.coding_plan import build_change_plan
from cfh_disposition.coding_repo import inspect_repository


def test_repository_inspection_is_read_only_and_ignores_generated_dirs(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('ok')", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok(): assert True", encoding="utf-8")
    ignored = tmp_path / "node_modules"
    ignored.mkdir()
    (ignored / "huge.js").write_text("ignored", encoding="utf-8")

    before = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())
    snapshot = inspect_repository(tmp_path)
    after = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())

    assert before == after
    assert "README.md" in snapshot.key_files
    assert "app.py" in snapshot.python_files
    assert "tests/test_app.py" in snapshot.test_files
    assert all("node_modules" not in path for path in snapshot.files)


def test_change_plan_uses_existing_repo_and_preserves_safety_boundary(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    (tmp_path / "dashboard.py").write_text("", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_dashboard.py").write_text("", encoding="utf-8")

    ticket = build_ticket("Add a mobile buyer dashboard and test it")
    plan = build_change_plan(ticket, inspect_repository(tmp_path))

    assert plan.ticket_id == ticket.ticket_id
    assert "dashboard.py" in plan.likely_areas
    assert "pytest -q" in plan.tests_to_run
    assert any("feature branch" in note for note in plan.safety_notes)
    assert any("Do not deploy" in note for note in plan.safety_notes)


def test_inspector_rejects_missing_repository_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    try:
        inspect_repository(missing)
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("Missing repository path must fail closed.")
