"""Fictional preservation inventories: no runtime/business connectors."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('preflight', Path(__file__).parents[1] / 'scripts/gordon_local_preflight.py')
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


@pytest.fixture
def setup(tmp_path):
    names = ['src/example.py', 'docs/NEXT_TASK.md', 'docs/SESSION_STATE.md', '.commandcore-runtime/evidence.json']
    baseline = {}
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fictional baseline')
        baseline[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return tmp_path, baseline, set(names[:3]), {names[3]}


def inspect(setup, extra=(), tracked_extra=()):
    root, baseline, tracked, ignored = setup
    return preflight.preservation(root, baseline, tracked=tracked | set(tracked_extra), ignored=ignored,
                                  discovered=set(baseline) | set(extra))


def test_runtime_change_recorded_without_mutation(setup):
    root, _, _, _ = setup
    path = root / '.commandcore-runtime/evidence.json'
    path.write_bytes(b'new fictional review evidence')
    before = path.read_bytes()
    report = inspect(setup)
    assert report['status'] == 'PASS'
    row = report['runtime_evidence'][0]
    assert row['classification'] == 'MUTABLE_RUNTIME_EVIDENCE'
    assert row['changed_since_baseline'] and row['sha256'] == hashlib.sha256(before).hexdigest()
    assert row['path'] == str(path) and row['size'] == len(before) and row['mtime_utc']
    assert path.read_bytes() == before


@pytest.mark.parametrize('name', ['src/example.py', 'docs/NEXT_TASK.md', 'docs/SESSION_STATE.md'])
def test_immutable_changes_block(setup, name):
    (setup[0] / name).write_bytes(b'changed')
    report = inspect(setup)
    assert report['status'] == 'BLOCK'
    assert {'path': name, 'reason': 'IMMUTABLE_FILE_CHANGED'} in report['errors']


@pytest.mark.parametrize('name', ['unexpected.txt', '.unknown/file', '.commandcore-runtime/unknown.json'])
def test_unknown_files_block(setup, name):
    assert inspect(setup, extra=[name])['status'] == 'BLOCK'


def test_tracked_runtime_is_not_exempt(setup):
    name = '.commandcore-runtime/evidence.json'
    (setup[0] / name).write_bytes(b'changed tracked configuration')
    assert inspect(setup, tracked_extra=[name])['status'] == 'BLOCK'


def test_missing_runtime_preserved_as_block(setup):
    (setup[0] / '.commandcore-runtime/evidence.json').unlink()
    assert inspect(setup)['status'] == 'BLOCK'


@pytest.mark.parametrize('which', ['commit', 'branch', 'path'])
def test_gordon_identity_mismatch_blocks(tmp_path, monkeypatch, which):
    monkeypatch.setattr(preflight, 'git', lambda root, *args: 'wrong' if which in {'commit', 'branch'} and args[-1] ==
                        ('HEAD' if which == 'commit' else '--show-current') else ('expected' if args[-1] == 'HEAD' else 'branch'))
    with pytest.raises(ValueError):
        preflight.verify_identity(tmp_path, tmp_path / 'wrong' if which == 'path' else tmp_path, 'expected', 'branch')
