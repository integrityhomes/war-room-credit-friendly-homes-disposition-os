"""Coordinated bounded adapter/caller tests; fictional isolated state only."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from check_gordon_caller import no_live_io  # noqa: F401 -- autouse production I/O barrier

from cfh_disposition import gordon_local_caller as module
from cfh_disposition.gordon_local_caller import SyntheticGordonCaller


@pytest.fixture
def bounded(tmp_path):
    authority = {}
    caller = SyntheticGordonCaller.create_bounded(tmp_path / 'synthetic', os.environ['GORDON_CHECKOUT'], authority)
    return caller, authority


def reopen(caller, authority):
    return SyntheticGordonCaller(caller.home, caller.checkout, synthetic_approvals=authority)


def approved(caller, authority):
    ref = str(uuid4())
    job = caller.enqueue_operation('apply_change', approval_ref=ref)
    authority[ref] = {'job_id': job['id'], 'operation': 'apply_change', 'workspace': str((caller.home / 'fixture').resolve()),
        'files': ['synthetic_change.py'], 'synthetic_only': True, 'expires_at': time.time() + 300,
        'before_sha256': hashlib.sha256(b'VALUE = 1\n').hexdigest(), 'after_sha256': hashlib.sha256(b'VALUE = 2\n').hexdigest()}
    return job


def test_complete_durable_flow(bounded):
    caller, authority = bounded
    target = caller.home / 'fixture/synthetic_change.py'
    for operation in ('inspect', 'propose_change'):
        job = caller.enqueue_operation(operation)
        result = caller.dispatch(job['id'])
        assert result['state'] == 'completed' and not result['response']['result']['files_changed']
        assert target.read_bytes() == b'VALUE = 1\n'
    job = approved(caller, authority)
    original = module.existing_adapter
    def adapter(*args, **kwargs):
        row = json.loads(caller.path.read_bytes())['jobs'][job['id']]
        assert row['state'] == 'dispatched' and row['bounded_request']['operation'] == 'apply_change'
        assert target.read_bytes() == b'VALUE = 1\n'
        return original(*args, **kwargs)
    with patch.object(module, 'existing_adapter', side_effect=adapter):
        done = caller.dispatch(job['id'])
    assert done['state'] == 'completed' and target.read_bytes() == b'VALUE = 2\n'
    assert done['response']['job_id'] == job['id']
    assert done['response']['result']['approval_ref'] == job['bounded_request']['approval_ref']
    restarted = reopen(caller, authority)
    assert restarted.recover()[job['id']] == done
    with patch.object(module, 'existing_adapter', side_effect=AssertionError('Replay')):
        assert restarted.dispatch(job['id']) == done
    for operation in ('run_validation', 'report_result'):
        row = restarted.enqueue_operation(operation)
        result = restarted.dispatch(row['id'])
        assert result['state'] == 'completed'
    assert result['response']['result']['prior_results']
    assert json.loads(caller.path.read_bytes())['jobs'][job['id']] == done


@pytest.mark.parametrize('bad', ['missing', 'stale', 'wrong_job', 'wrong_workspace', 'forged', 'scope'])
def test_approval_blocks_across_restart(bounded, bad):
    caller, authority = bounded
    job = approved(caller, authority)
    ref = job['bounded_request']['approval_ref']
    if bad in {'missing', 'forged'}:
        authority.clear()
    else:
        key, value = {'stale': ('expires_at', 0), 'wrong_job': ('job_id', str(uuid4())),
                      'wrong_workspace': ('workspace', str(caller.home)), 'scope': ('files', ['other.py'])}[bad]
        authority[ref][key] = value
    blocked = caller.dispatch(job['id'])
    assert blocked['state'] == 'blocked_for_approval'
    assert not blocked['response']['actions_attempted']
    with patch.object(module, 'existing_adapter', side_effect=AssertionError('Blocked job resumed')):
        assert reopen(caller, authority).dispatch(job['id']) == blocked
    assert (caller.home / 'fixture/synthetic_change.py').read_bytes() == b'VALUE = 1\n'


@pytest.mark.parametrize('kwargs', [{'operation': 'unknown'}, {'operation': 'apply_change', 'files': ['../outside']},
    {'operation': 'apply_change', 'files': ['C:/outside.py']}, {'operation': 'run_validation', 'validation_ids': ['git push']},
    {'operation': 'run_validation', 'validation_ids': ['python -c arbitrary']}, {'operation': 'apply_change', 'approval_ref': 'forged'}])
def test_invalid_requests_fail_before_journal_or_adapter(bounded, kwargs):
    caller, _ = bounded
    before = caller.path.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        caller.enqueue_operation(**kwargs)
    assert caller.path.read_bytes() == before


@pytest.mark.parametrize('phase', ['dispatched', 'adapter_return', 'received'])
def test_process_crash_mutation_recovery(bounded, phase):
    caller, authority = bounded
    job = approved(caller, authority)
    code = '''
import json,os,sys
sys.path.insert(0,sys.argv[1])
from cfh_disposition.gordon_local_caller import SyntheticGordonCaller
from cfh_disposition.corepilot_gordon import GordonConnection
c=SyntheticGordonCaller(sys.argv[2],sys.argv[3],synthetic_approvals=json.loads(sys.argv[6]))
phase=sys.argv[5]
original=c._transition
def transition(state,job,status):
    original(state,job,status)
    if status==phase: os._exit(73)
c._transition=transition
original_call=GordonConnection.bounded
def call(self,*args):
    result=original_call(self,*args)
    if phase=='adapter_return': os._exit(73)
    return result
GordonConnection.bounded=call
c.dispatch(sys.argv[4])
'''
    env = {k: v for k, v in os.environ.items() if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    run = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(Path(module.__file__).resolve().parents[1]),
        str(caller.home), str(caller.checkout), job['id'], phase, json.dumps(authority)],
        env=env, cwd=caller.home, capture_output=True, timeout=30)
    assert run.returncode == 73, run.stderr.decode()
    recovered = reopen(caller, authority).recover()[job['id']]
    assert recovered['state'] == ('completed' if phase == 'received' else 'blocked_uncertain')
    assert (caller.home / 'fixture/synthetic_change.py').read_bytes() == (b'VALUE = 1\n' if phase == 'dispatched' else b'VALUE = 2\n')
    with patch.object(module, 'existing_adapter', side_effect=AssertionError('Uncertain mutation replayed')):
        assert reopen(caller, authority).dispatch(job['id']) == recovered


def test_request_identity_conflict(bounded):
    caller, _ = bounded
    caller.enqueue_operation('apply_change', approval_ref=str(uuid4()))
    with pytest.raises(ValueError):
        caller.enqueue_operation('apply_change', approval_ref=str(uuid4()))


def test_default_disabled_and_validation_failure(bounded, tmp_path):
    caller, _ = bounded
    plain = SyntheticGordonCaller.create(tmp_path / 'old_mode', caller.checkout)
    with pytest.raises(ValueError):
        plain.enqueue_operation('apply_change')
    assert module.PRODUCTION_ENABLED is False
    job = caller.enqueue_operation('run_validation')
    failed = caller.dispatch(job['id'])
    assert failed['state'] == 'failed' and failed['response']['error']['code'] == 'validation_failed'
