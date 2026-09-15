"""Read-only local preservation gate; runtime evidence is recorded, never repaired."""
import hashlib
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

RUNTIME = '.commandcore-runtime/'
# Exact existing lint outputs, pinned for this local preflight; no directory wildcard.
KNOWN_TOOLING = {'commandcore': {'.ruff_cache/.gitignore': '9e3a60f1e6ec4ae60215c11d54b171392745ec25e9dded433d5bd921363af316',
                 '.ruff_cache/0.16.5/11331049746717968553': '08fcb677e98a6d0076d603c7b35935b2c5d8afc6c3ce746f03a4c02b55e33716',
                 '.ruff_cache/0.16.5/15591840843662087481': '1e874bcf8636f9d96cb272dbe1f53b1ea279d6d0776f1f50d52e58924f1fdf0f',
                 '.ruff_cache/0.16.5/17612396333966990055': 'aac2bc224c0a003a34b420a75855363f9faf7b903ed401ac5844f5741e439543',
                 '.ruff_cache/0.16.5/2861474481087974589': 'dd03670a1e767263e82879bb50e96a64bcbe5e3f5ce5c6b1c9920c942076506d',
                 '.ruff_cache/0.16.5/596441018029075572': 'b21be6d56439bc5b348244f326ad562c5f1c52f4dfdc098ca597ac8818252d2e',
                 '.ruff_cache/CACHEDIR.TAG': '5953156d7e0c564a427251316eaf26f8870e6483ae2197f916b630e4f93e31ae'},
 'gordon': {'workspace/bot_dev/.ruff_cache/.gitignore': '9e3a60f1e6ec4ae60215c11d54b171392745ec25e9dded433d5bd921363af316',
            'workspace/bot_dev/.ruff_cache/0.16.5/2418765212826109089': '859b30530062435ee702ff97ae35125b55659bbd50ef3fe7cd135ba7d71c1970',
            'workspace/bot_dev/.ruff_cache/0.16.5/5210653408202950308': '4fea38a19a7a29aab4ce13ce45b5b2aa74105a2645be3b6d1e82bc145a87ba97',
            'workspace/bot_dev/.ruff_cache/0.16.5/8454782866863667589': 'f3d2f782e2e8259d2855c286c2fdcae086c89bafc12047de4da49ffce064ddd5',
            'workspace/bot_dev/.ruff_cache/CACHEDIR.TAG': '5953156d7e0c564a427251316eaf26f8870e6483ae2197f916b630e4f93e31ae'}}


def git(root, *args):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args], capture_output=True, check=True)
    return result.stdout.decode('utf-8')


def verify_identity(root, expected_path, expected_commit, expected_branch):
    root = Path(root)
    if root.absolute() != Path(expected_path).absolute() or root.resolve() != Path(expected_path).absolute():
        raise ValueError('Repository path mismatch')
    if git(root, 'rev-parse', 'HEAD').strip() != expected_commit:
        raise ValueError('Commit mismatch')
    if git(root, 'branch', '--show-current').strip() != expected_branch:
        raise ValueError('Branch mismatch')


def evidence(path):
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Linked evidence path')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    current = path.stat()
    def stamps(st):
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns
    if stamps(before) != stamps(after) or stamps(after) != stamps(current):
        raise ValueError('Evidence changed during inspection; review and retry')
    return {'path': str(path.absolute()), 'size': current.st_size,
            'mtime_utc': datetime.fromtimestamp(current.st_mtime, UTC).isoformat(), 'sha256': digest}


def preservation(root, baseline, *, tracked, ignored, discovered):
    """Explicit inventory inputs permit synthetic tests without any live adapters.

    Only known baseline files can receive the mutable-runtime classification.
    Tracked files always remain strict, even beneath the runtime directory.
    """
    root = Path(root)
    baseline = {name.replace('\\', '/'): value for name, value in baseline.items()}
    tracked, ignored, discovered = map(set, (tracked, ignored, discovered))
    errors, runtime = [], []
    for name in sorted(discovered - set(baseline)):
        errors.append({'path': name, 'reason': 'UNKNOWN_FILE'})
    for name, digest in baseline.items():
        try:
            item = evidence(root / name)
        except (OSError, ValueError):
            errors.append({'path': name, 'reason': 'MISSING_OR_UNSTABLE_FILE'})
            continue
        if name.startswith(RUNTIME) and name in ignored and name not in tracked:
            runtime.append(dict(item, classification='MUTABLE_RUNTIME_EVIDENCE', baseline_sha256=digest,
                                changed_since_baseline=item['sha256'] != digest))
        elif item['sha256'] != digest:
            errors.append({'path': name, 'reason': 'IMMUTABLE_FILE_CHANGED'})
    return {'status': 'BLOCK' if errors else 'PASS', 'errors': errors, 'runtime_evidence': runtime}


def inspect_preservation(root, baseline, *, known_excluded=()):
    """Excluded directories must be named known environment/cache limitations.

    They are reported, not silently accepted as verified source. No writes occur.
    """
    def names(*args):
        return {n for n in git(root, 'ls-files', '-z', *args).split('\0') if n}
    tracked = names()
    ordinary = names('--others', '--exclude-standard')
    ignored = names('--others', '--ignored', '--exclude-standard')
    discovered = tracked | ordinary | ignored
    excluded = {n for n in discovered if any(n.startswith(prefix) for prefix in known_excluded)}
    # Never exempt tracked source/configuration based on an environment prefix.
    excluded -= tracked
    result = preservation(root, baseline, tracked=tracked, ignored=ignored, discovered=discovered - excluded)
    result['known_inventory_exclusions'] = list(known_excluded)
    result['excluded_file_count'] = len(excluded)
    return result


def local_report():
    """Exact owner-approved local versions; no baseline update or test execution."""
    import json

    cc = Path(__file__).resolve().parents[1]
    original = Path('C:/Users/msb75/CodingBot/workspace/CommandCore')
    original_gordon = Path('C:/Users/msb75/CodingBot')
    bounded = Path('C:/Users/msb75/AppData/Local/Temp/Gordon-bounded-repair-adapter')
    expected_cc = Path('C:/Users/msb75/AppData/Local/Temp/CommandCore-gordon-bounded-repair-build')
    verify_identity(cc, expected_cc, 'e69855e2fb96e59401dd3fce526c2a32dae01015', 'codex/gordon-bounded-repair-build')
    verify_identity(bounded, bounded, '77d62f225aa2cd63621c92768df02d5336fdc47d', 'codex/gordon-bounded-repair-adapter')
    verify_identity(original_gordon, original_gordon, '6f87bd47f722ac9c50e02e2a715f0c3296af940b', 'controlled-self-development')
    verify_identity(original, original, 'a1acd96ee6dbdd9d039fb52cc58e0fc9af116822', 'feature/meta-compliance-guards')
    for root in (cc, bounded, original_gordon):
        if git(root, 'diff', 'HEAD', '--name-only').strip():
            raise ValueError('Unexpected tracked changes')
    corrections = {'scripts/gordon_local_preflight.py', 'tests/test_gordon_local_preflight.py'}
    for root, allowed in ((cc, corrections), (bounded, set())):
        extra = set(filter(None, git(root, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')))
        if extra != allowed:
            raise ValueError('Unexpected untracked files in isolated worktree')
        ignored = set(filter(None, git(root, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z').split('\0')))
        # These exact existing lint-cache directories were created by prior verified runs.
        expected = KNOWN_TOOLING['commandcore' if root == cc else 'gordon']
        if ignored != set(expected):
            raise ValueError('Unknown ignored files in isolated worktree')
        if any(evidence(root / name)['sha256'] != digest for name, digest in expected.items()):
            raise ValueError('Known tooling evidence changed')
    manifest_path = Path('C:/Users/msb75/AppData/Local/Temp/gordon-bounded-preservation.json')
    manifest = json.loads(manifest_path.read_text())
    reports = {}
    for root in (original, original_gordon / 'workspace/bot_dev'):
        saved = manifest[str(root)]
        # Retain the prior baseline's explicit environment and inaccessible-cache
        # limitations. No new unknown file outside these known exclusions is allowed.
        excluded = ['.venv/', 'node_modules/'] if root == original else []
        for path in saved['unreadable']:
            relative = Path(path).relative_to(root).as_posix()
            excluded.extend([relative + '/'])
        reports[str(root)] = inspect_preservation(root, saved['files'], known_excluded=excluded)
    import ast

    tree = ast.parse((cc / 'src/cfh_disposition/gordon_local_caller.py').read_bytes())
    flags = [node.value.value for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
             and any(isinstance(target, ast.Name) and target.id == 'PRODUCTION_ENABLED' for target in node.targets)]
    if flags != [False]:
        raise ValueError('Production-disabled flag not verified')
    adapter = bounded / 'workspace/bot_dev/app/local_adapter.py'
    if adapter.resolve() != adapter or not adapter.is_file():
        raise ValueError('Adapter path mismatch')
    return {'status': 'PASS' if all(r['status'] == 'PASS' for r in reports.values()) else 'BLOCK',
            'commandcore_commit': git(cc, 'rev-parse', 'HEAD').strip(),
            'gordon_commit': git(bounded, 'rev-parse', 'HEAD').strip(), 'adapter_path': str(adapter),
            'authorized_preflight_files': sorted(corrections), 'preservation': reports}


if __name__ == '__main__':
    import json

    report = local_report()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)
