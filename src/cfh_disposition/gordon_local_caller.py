"""Disabled-for-production caller: generated synthetic fixtures and existing adapter only.

No user paths, payloads, credentials, approval grants, business stores or executors.
Atomic local snapshots are technical journal state, not canonical business records.
"""
import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from .corepilot_gordon import INSPECTIONS, GordonConnection, GordonJob, existing_adapter
from .property_change_cache import exclusive_check

FIXTURE = b'Fictional local inspection fixture.\n'
BOUNDED_OPERATIONS = ('inspect', 'propose_change', 'apply_change', 'run_validation', 'report_result')
LANES = (*INSPECTIONS, 'repair', *('bounded_' + op for op in BOUNDED_OPERATIONS))
STATES = {'queued', 'dispatched', 'received', 'completed', 'failed', 'blocked_for_approval', 'blocked_uncertain'}
PRODUCTION_ENABLED = False
MAX_STATE_BYTES = 1024 * 1024


def _references(namespace):
    # Same canonical task reference shape and corepilot-ID convention, fictional only.
    return {lane: {'task_id': 'corepilot-' + hashlib.sha256(f'{namespace}:{lane}'.encode()).hexdigest()} for lane in LANES}


def _safe_tree(home):
    for p in (home, *home.parents, *home.rglob('*')):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Linked sandbox paths are forbidden')


def _atomic(path, value):
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    if len(data) > MAX_STATE_BYTES:
        raise ValueError('Caller journal capacity reached; preserve and review')
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Directory fsync is unavailable through this interface on Windows.
        if os.name != 'nt':
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temporary.exists():
            temporary.unlink()


class SyntheticGordonCaller:
    """No production mode. Reopen only a sandbox created by create()."""

    @classmethod
    def create(cls, home, checkout):
        home = Path(home).absolute()
        # Never populate an existing project or existing output directory.
        for p in home.parents:
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                raise ValueError('Linked sandbox parent')
        home.mkdir(parents=False, exist_ok=False)
        root = home / 'fixture'
        root.mkdir()
        for name in set(INSPECTIONS.values()):
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(FIXTURE)
        (home / 'audit').mkdir()
        _atomic(home / 'caller.json', {'version': 1, 'synthetic_only': True, 'namespace': str(uuid4()), 'jobs': {}})
        return cls(home, checkout)

    @classmethod
    def create_bounded(cls, home, checkout, synthetic_approvals):
        if not isinstance(synthetic_approvals, dict):
            raise ValueError("Trusted synthetic authority required")
        caller = cls.create(home, checkout)
        (caller.home / "fixture/synthetic_change.py").write_bytes(b"VALUE = 1\n")
        return cls(home, checkout, synthetic_approvals=synthetic_approvals)

    def __init__(self, home, checkout, *, synthetic_approvals=None):
        self.synthetic_approvals = synthetic_approvals
        self.home = Path(home).absolute()
        self.path = self.home / 'caller.json'
        self.checkout = Path(checkout)
        self._validate_fixture()
        self._load()

    def _validate_fixture(self):
        _safe_tree(self.home)
        root = self.home / 'fixture'
        actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
        expected = set(INSPECTIONS.values())
        if self.synthetic_approvals is not None:
            expected.add('synthetic_change.py')
        if actual != expected or any((root / name).stat().st_nlink != 1 or
                (root / name).read_bytes() not in ({b'VALUE = 1\n', b'VALUE = 2\n'} if name == 'synthetic_change.py' else {FIXTURE})
                for name in actual):
            raise ValueError('Only generated synthetic fixtures may be inspected')

    def _load(self):
        _safe_tree(self.home)
        if self.path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError('Caller journal exceeds bound')
        state = json.loads(self.path.read_bytes())
        if set(state) != {'version', 'synthetic_only', 'namespace', 'jobs'} or state['version'] != 1 or state['synthetic_only'] is not True:
            raise ValueError('Invalid synthetic journal')
        ns = UUID(state['namespace'])
        refs = _references(str(ns))
        if not isinstance(state['jobs'], dict) or len(state['jobs']) > len(LANES):
            raise ValueError('Invalid job registry')
        for key, row in state['jobs'].items():
            fields = {'id', 'reference', 'lane', 'identity', 'state', 'history', 'response', 'error'}
            if 'bounded_request' in row:
                fields.add('bounded_request')
                self._validate_request(row['bounded_request'])
                if row['lane'] != 'bounded_' + row['bounded_request']['operation']:
                    raise ValueError('Conflicting operation identity')
            if set(row) != fields:
                raise ValueError('Invalid job fields')
            lane = row['lane']
            expected = str(uuid5(ns, lane))
            if lane not in refs or row['reference'] != refs[lane] or key != expected or row['id'] != key:
                raise ValueError('Unknown or conflicting job reference')
            if row['identity'] != {'idempotency_key': key, 'correlation_id': str(uuid5(ns, lane + ':correlation'))}:
                raise ValueError('Invalid job identity')
            if row['state'] not in STATES or not row['history'] or row['history'][-1]['state'] != row['state']:
                raise ValueError('Invalid job lifecycle')
            if row['state'] in {'received', 'completed'} and not isinstance(row['response'], dict):
                raise ValueError('Missing persisted response')
        return state

    @property
    def references(self):
        return _references(self._load()['namespace'])

    def _transition(self, state, job, status):
        job['state'] = status
        job['history'].append({'state': status, 'at': datetime.now(UTC).isoformat()})
        _atomic(self.path, state)

    def enqueue(self, reference):
        with exclusive_check(self.path):
            state = self._load()
            matching = [lane for lane, ref in _references(state['namespace']).items() if reference == ref]
            if len(matching) != 1:
                raise ValueError('Unknown synthetic canonical task reference')
            lane = matching[0]
            ns = UUID(state['namespace'])
            key = str(uuid5(ns, lane))
            if key not in state['jobs']:
                job = {'id': key, 'reference': deepcopy(reference), 'lane': lane,
                       'identity': {'idempotency_key': key, 'correlation_id': str(uuid5(ns, lane + ':correlation'))},
                       'state': 'queued', 'history': [], 'response': None, 'error': None}
                state['jobs'][key] = job
                self._transition(state, job, 'queued' if lane in INSPECTIONS else 'blocked_for_approval')
            return deepcopy(state['jobs'][key])

    @staticmethod
    def _validate_request(request):
        expected = {'job_type', 'operation', 'files', 'validation_ids', 'approval_ref'}
        if not isinstance(request, dict) or set(request) != expected or request['job_type'] != 'technical.synthetic_change':
            raise ValueError('Unknown request')
        if request['operation'] not in BOUNDED_OPERATIONS or request['files'] != ['synthetic_change.py']:
            raise ValueError('Unknown operation or file scope')
        commands = ['python_syntax', 'expected_value'] if request['operation'] == 'run_validation' else []
        if request['validation_ids'] != commands:
            raise ValueError('Validation not allowlisted')
        if request['approval_ref'] is not None:
            UUID(request['approval_ref'])

    def enqueue_operation(self, operation, *, approval_ref=None, files=None, validation_ids=None):
        if self.synthetic_approvals is None:
            raise ValueError('Bounded mode is disabled')
        request = {'job_type': 'technical.synthetic_change', 'operation': operation,
                   'files': ['synthetic_change.py'] if files is None else files,
                   'validation_ids': (['python_syntax', 'expected_value'] if operation == 'run_validation' else [])
                       if validation_ids is None else validation_ids, 'approval_ref': approval_ref}
        self._validate_request(request)
        initial = self.enqueue(self.references['bounded_' + operation])
        with exclusive_check(self.path):
            state = self._load()
            job = state['jobs'][initial['id']]
            if 'bounded_request' in job:
                if job['bounded_request'] != request:
                    raise ValueError('Job identity already bound to another request')
            else:
                job['bounded_request'] = deepcopy(request)
                self._transition(state, job, 'queued')
            return deepcopy(job)

    def _finish_received(self, state, job):
        response = job['response']
        status = response.get('status')
        target = 'completed' if status == 'completed' else 'blocked_for_approval' if status == 'approval_required' else 'failed'
        job['error'] = response.get('error')
        self._transition(state, job, target)

    def recover(self):
        with exclusive_check(self.path):
            state = self._load()
            for job in state['jobs'].values():
                if job['state'] == 'dispatched':
                    job['error'] = {'code': 'dispatch_outcome_unknown'}
                    self._transition(state, job, 'blocked_uncertain')
                elif job['state'] == 'received':
                    self._finish_received(state, job)
            return deepcopy(state['jobs'])

    def dispatch(self, job_id):
        with exclusive_check(self.path):
            self._validate_fixture()
            state = self._load()
            if job_id not in state['jobs']:
                raise ValueError('Unknown job ID')
            job = state['jobs'][job_id]
            if job['state'] == 'dispatched':
                job['error'] = {'code': 'dispatch_outcome_unknown'}
                self._transition(state, job, 'blocked_uncertain')
            if job['state'] == 'received':
                self._finish_received(state, job)
            if job['state'] != 'queued':
                return deepcopy(job)
            if job['lane'] not in INSPECTIONS and 'bounded_request' not in job:
                self._transition(state, job, 'blocked_for_approval')
                return deepcopy(job)
            # Durable dispatch intent BEFORE loading/calling the one existing adapter.
            self._transition(state, job, 'dispatched')
            try:
                if 'bounded_request' in job:
                    if self.synthetic_approvals is None:
                        raise ValueError('Synthetic authority unavailable')
                    adapter = existing_adapter(self.checkout, self.home / 'fixture', self.home / 'audit' / 'gordon.jsonl',
                                               synthetic_approvals=self.synthetic_approvals)
                    outcome = GordonConnection(adapter).bounded(job['bounded_request'], GordonJob(**job['identity']))
                else:
                    adapter = existing_adapter(self.checkout, self.home / 'fixture', self.home / 'audit' / 'gordon.jsonl')
                    outcome = GordonConnection(adapter).inspect(job['lane'], GordonJob(**job['identity']))
            except Exception:
                # Exception details may contain sensitive data; never persist them.
                job['error'] = {'code': 'dispatch_outcome_unknown'}
                self._transition(state, job, 'blocked_uncertain')
                return deepcopy(job)
            job['response'] = outcome
            self._transition(state, job, 'received')
            self._finish_received(state, job)
            return deepcopy(job)
