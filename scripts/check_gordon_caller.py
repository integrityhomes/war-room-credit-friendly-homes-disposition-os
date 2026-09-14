"""Explicit synthetic real-Gordon caller checks; never part of live ingestion."""
import json
import os
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from cfh_disposition import gordon_local_caller as module
from cfh_disposition.corepilot_gordon import existing_adapter
from cfh_disposition.gordon_local_caller import SyntheticGordonCaller


@pytest.fixture(autouse=True)
def no_live_io(monkeypatch):
    attempts = []
    active = [True]
    def denied(*args, **kwargs):
        attempts.append('network')
        raise AssertionError('External services forbidden')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    def audit(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes)):
            name = os.fsdecode(args[0]).replace(chr(92), '/').lower()
            original = 'c:/users/msb75/codingbot/workspace/commandcore/'
            if ('secrets.toml' in name or '/.env' in name
                    or (name.startswith(original) and not name.startswith(original + '.venv/'))):
                attempts.append('production_file')
                raise AssertionError('Production files forbidden')
    sys.addaudithook(audit)
    try:
        yield
    finally:
        active[0] = False
    assert attempts == []


@pytest.fixture
def caller(tmp_path):
    return SyntheticGordonCaller.create(tmp_path / 'synthetic', os.environ['GORDON_CHECKOUT'])


def reopen(caller):
    return SyntheticGordonCaller(caller.home, caller.checkout)


def test_stable_identity_and_queued_before_dispatch(caller):
    job = caller.enqueue(caller.references['system'])
    assert job['state'] == 'queued'
    assert reopen(caller).enqueue(caller.references['system']) == job
    def checked(*args):
        stored = json.loads(caller.path.read_bytes())['jobs'][job['id']]
        assert [e['state'] for e in stored['history']] == ['queued', 'dispatched']
        return existing_adapter(*args)
    with patch.object(module, 'existing_adapter', side_effect=checked) as invoked:
        result = caller.dispatch(job['id'])
        assert invoked.call_count == 1
    assert result['state'] == 'completed'
    response = result['response']
    assert response['accepted'] and response['job_id'] and response['audit']['durable']
    assert response['correlation_id'] == job['identity']['correlation_id']
    assert response['actions_attempted'] == [{'step': 1, 'command': 'read', 'status': 'completed'}]
    assert response['cost'] == {'api_calls': 0, 'models': [], 'cost_usd': 0.0}
    assert [e['state'] for e in result['history']] == ['queued', 'dispatched', 'received', 'completed']
    assert reopen(caller).recover()[job['id']] == result


def test_completed_never_dispatches_twice(caller):
    job = caller.enqueue(caller.references['system'])
    first = caller.dispatch(job['id'])
    with patch.object(module, 'existing_adapter', side_effect=AssertionError('Duplicate')) as blocked:
        assert reopen(caller).dispatch(job['id']) == first
        blocked.assert_not_called()
    assert len([json.loads(line) for line in (caller.home/'audit/gordon.jsonl').read_text().splitlines()
                if json.loads(line)['event'] == 'accepted']) == 1


def test_queued_restart_can_dispatch(caller):
    job = caller.enqueue(caller.references['connector'])
    assert reopen(caller).recover()[job['id']]['state'] == 'queued'
    assert reopen(caller).dispatch(job['id'])['state'] == 'completed'


def test_failed_response_traceable(caller):
    job = caller.enqueue(caller.references['system'])
    def failed(*args):
        adapter = existing_adapter(*args)
        adapter._execute = lambda *a: (_ for _ in ()).throw(RuntimeError('private-error-not-for-journal'))
        return adapter
    with patch.object(module, 'existing_adapter', side_effect=failed):
        result = caller.dispatch(job['id'])
    assert result['state'] == 'failed' and result['error'] == {'code': 'execution_failed'}
    assert result['response']['job_id']
    assert 'private-error' not in caller.path.read_text()
    with patch.object(module, 'existing_adapter') as invoked:
        assert reopen(caller).dispatch(job['id']) == result
        invoked.assert_not_called()


def test_approval_blocked_before_adapter_and_after_restart(caller):
    job = caller.enqueue(caller.references['repair'])
    assert job['state'] == 'blocked_for_approval'
    with patch.object(module, 'existing_adapter') as invoked:
        assert caller.dispatch(job['id']) == job
        assert reopen(caller).recover()[job['id']] == job
        assert reopen(caller).dispatch(job['id']) == job
        invoked.assert_not_called()
    state = json.loads(caller.path.read_bytes())
    state['jobs'][job['id']]['approved_by'] = 'Shawn'
    caller.path.write_text(json.dumps(state))
    with pytest.raises(ValueError):
        reopen(caller)


@pytest.mark.parametrize('ref', [{}, {'task_id': 'unknown'}, {'task_id': '../credentials'}, {'deal_id': 'real'}, {'task_id': 'fake', 'approved_by': 'Sabrina'}])
def test_unknown_references_fail_closed(caller, ref):
    before = caller.path.read_bytes()
    with pytest.raises(ValueError):
        caller.enqueue(ref)
    with pytest.raises(ValueError):
        caller.dispatch('unknown')
    assert caller.path.read_bytes() == before


def test_atomic_failure_preserves_original_queue(caller):
    before = caller.path.read_bytes()
    with patch.object(module.os, 'replace', side_effect=OSError('synthetic-disk-error')):
        with pytest.raises(OSError):
            caller.enqueue(caller.references['system'])
    assert caller.path.read_bytes() == before and reopen(caller).recover() == {}


@pytest.mark.parametrize('change', ['fixture', 'corruption', 'identity'])
def test_invalid_local_state_fails_without_adapter(caller, change):
    job = caller.enqueue(caller.references['system'])
    if change == 'fixture':
        (caller.home/'fixture/pyproject.toml').write_text('Non-synthetic input')
    elif change == 'corruption':
        caller.path.write_text('{broken')
    else:
        state = json.loads(caller.path.read_bytes())
        state['jobs'][job['id']]['identity']['idempotency_key'] = 'unknown'
        caller.path.write_text(json.dumps(state))
    with patch.object(module, 'existing_adapter') as invoked:
        with pytest.raises(ValueError):
            reopen(caller).dispatch(job['id'])
        invoked.assert_not_called()


@pytest.mark.parametrize('crash_at', ['dispatched', 'adapter_return', 'received'])
def test_real_process_crash_and_recovery(caller, crash_at):
    job = caller.enqueue(caller.references['system'])
    source = str(Path(module.__file__).resolve().parents[1])
    code = '''
import os, sys
sys.path.insert(0, sys.argv[1])
from cfh_disposition.gordon_local_caller import SyntheticGordonCaller
from cfh_disposition.corepilot_gordon import GordonConnection
c = SyntheticGordonCaller(sys.argv[2], sys.argv[3])
phase = sys.argv[5]
original = c._transition
def transition(state, job, status):
    original(state, job, status)
    if status == phase:
        os._exit(73)
c._transition = transition
original_inspect = GordonConnection.inspect
def inspect(self, *args):
    result = original_inspect(self, *args)
    if phase == 'adapter_return':
        os._exit(73)
    return result
GordonConnection.inspect = inspect
c.dispatch(sys.argv[4])
'''
    env = {k: v for k, v in os.environ.items() if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, source, str(caller.home), str(caller.checkout), job['id'], crash_at],
                            env=env, capture_output=True, timeout=30, cwd=caller.home)
    assert result.returncode == 73, result.stderr.decode()
    recovered = reopen(caller).recover()[job['id']]
    assert recovered['state'] == ('completed' if crash_at == 'received' else 'blocked_uncertain')
    assert recovered['identity'] == job['identity']
    with patch.object(module, 'existing_adapter') as invoked:
        assert reopen(caller).dispatch(job['id']) == recovered
        invoked.assert_not_called()
    journal = caller.home/'audit/gordon.jsonl'
    accepted = sum(json.loads(line)['event'] == 'accepted' for line in journal.read_text().splitlines()) if journal.exists() else 0
    assert accepted == (0 if crash_at == 'dispatched' else 1)


def test_no_production_mode_or_customer_input(caller):
    assert module.PRODUCTION_ENABLED is False
    assert {p.read_bytes() for p in (caller.home/'fixture').rglob('*') if p.is_file()} == {module.FIXTURE}
    with pytest.raises(TypeError):
        SyntheticGordonCaller(caller.home, caller.checkout, production=True)
    with pytest.raises(FileExistsError):
        SyntheticGordonCaller.create(caller.home, caller.checkout)
    with pytest.raises(TypeError):
        caller.enqueue(caller.references['system'], customer_data={'secret': 'fictional'})
    before = deepcopy(caller.references)
    assert before == reopen(caller).references
