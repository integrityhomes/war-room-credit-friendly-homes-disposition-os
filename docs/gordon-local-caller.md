# Disabled synthetic Gordon caller

This layer is local test infrastructure only. It is not imported by the production
page, does not load credentials or canonical records, and has no production-enable
or approval-resume argument. Existing Gordon and its read/list policy are unchanged.

## Architecture

`SyntheticGordonCaller` -> existing `GordonConnection.inspect` -> existing
`existing_adapter` -> audited Gordon `app/local_adapter.py`.
There is no alternate executor, second adapter, new CRM, or production scheduler.
The host supplies the trusted audited checkout. `create(new_directory, checkout)`
requires a nonexistent directory and writes fixed fictional source fixtures only.
`SyntheticGordonCaller(directory, checkout)` reopens it and verifies fixture bytes,
job references and persisted identity. Linked filesystem paths are rejected.

Each generated synthetic task reference has the existing `{"task_id":"corepilot-..."}`
shape. It is a fixture reference, never a newly created canonical business task.
The namespace identifies the sandbox; deterministic UUIDs identify each task's job
and correlation. These use the existing `GordonJob` idempotency/correlation format.
Gordon separately allocates its own job ID, persisted in the structured response.
This bounded harness supplies one task per supported inspection lane and one blocked
repair placeholder. New tasks require a new synthetic sandbox; there is no arbitrary
payload or real-record import API. Unknown task/job references fail closed.

## Persistence and recovery

All paths are inside the new synthetic output directory:

- `fixture/`: exactly the fixed fictional files allowed by CommandCore's inspections.
- `caller.json`: versioned, size-bounded technical snapshot, synthetic namespace,
  stable identities, task references, states/history and normalized response/error.
- `caller.lock`: existing OS source-lock helper, held through each dispatch.
- `audit/gordon.jsonl` and its lock: Gordon's original append-only durable journal,
  outside the inspection root. No Gordon audit is modified by the caller.

Snapshot writes use same-directory unique temporary files, flush/fsync, then atomic
replace. POSIX also fsyncs the directory; Windows directory durability across sudden
power loss is not guaranteed. Stale snapshots fail closed after detected corruption;
no automatic reset, deletion, rotation or replay is performed. The caller caps state
at 1 MiB; Gordon retains its existing 32 MiB audit bound. This is single-host locking,
not proof of distributed writer safety. Fixture/metadata validation is an accidental
misconfiguration barrier, not a security sandbox against an administrator modifying
trusted files or Python code.

| Persisted state | Restart behavior |
| --- | --- |
| queued | Remains queued; explicit local dispatch may proceed with the same IDs. |
| dispatched | Becomes blocked_uncertain; no retry, even if the worker never started. |
| received | Finalizes the already persisted response without another adapter call. |
| completed / failed | Returns the original outcome; no automatic retry. |
| blocked_for_approval | Stays blocked. No approval record or prompt can resume it here. |
| blocked_uncertain | Stays blocked pending a separately reviewed reconciliation process. |

Dispatch intent is durable before adapter construction or invocation. A response is
persisted as received before terminal finalization. Adapter exceptions are normalized
to an uncertain block; raw exception text is not journaled. Crashes cannot trigger an
automatic second execution. The original Gordon journal supplies a second duplicate
barrier but the caller conservatively does not redispatch uncertain work.

## Validation

Run the explicit real-adapter checks using the original Python environment with
this worktree as cwd, `GORDON_CHECKOUT` pointing to the audited existing checkout,
`PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, and:

```text
python -B -m pytest scripts/check_gordon_caller.py scripts/check_gordon_handshake.py tests/test_corepilot_gordon.py tests/test_corepilot_staff_routing.py -p no:cacheprovider --basetemp <fresh-disposable-directory> -ra
```

No Gordon checkout is copied. This suite stays outside the default offline simulator
because that simulator intentionally blocks real external-checkout/child-process
access. New caller tests assert no parent network/credential/original-project data
access; Gordon's existing worker blocks networking and receives only fictional paths
with a reduced environment. Actual process exits cover dispatch-before-call,
completed-worker-before-receipt, and receipt-before-finalization. Atomic write failure,
identity corruption, unknown references, failed outcomes and fake approval fields are
also tested. Results are recorded below after completion; the recovery documents are
intentionally untouched per owner instruction.

## Next separately reviewed step

Review this local caller/recovery contract and its limits. Then design an explicit,
bounded repair/build request and approval-verification contract using existing
canonical task/approval records and the existing Gordon interface. Define recovery
for uncertain execution before adding write capability. Do not implement activation,
change the read/list policy, add a production journal, or enable repair/build merely
because these tests pass.

## Results — 2026-09-14

Initial caller + real-adapter suite: 38 passed. Final suite with explicit caller I/O
assertions and adjacent staff/Gordon routing regressions: 102 passed / 0 failed
(18 caller cases, 20 existing handshake cases, 64 routing cases; overlapping runs).
Final output: `C:/Users/msb75/AppData/Local/Temp/gordon-caller-guarded-9586fe9ac47b4d17a47ddd198f9c4d51`.
Production I/O attempt assertions passed. Ruff and whitespace checks passed after a
single import-order correction. No full business simulator was run for this isolated
local caller change. Python 3.13.15 remains the host runtime versus project target 3.12.
No commit, merge, push or deployment. Work remains on `codex/gordon-local-caller`.

## Pre-PR verification — 2026-09-14

Revalidated all 102 selected caller/adapter/routing tests: 102 passed, 0 failed.
Repository-wide `ruff check .` and `git diff --check` passed. Review found no
second adapter, alternate execution path, production activation, external service
use, credential/customer-data logging, or automatic approval-resume path.

Publication is blocked by branch ancestry: fetched `origin/main` at `9de1e51`
does not contain `corepilot_gordon.py`. The caller branch inherits 14 local commits
and 112 changed files before this three-file caller commit. A PR to main would
therefore include unrelated earlier work. Preserve this scoped local commit and
resolve/review prerequisite integration history separately before publishing;
do not silently include that history or duplicate the missing integration.
No push, PR, merge or deployment was performed for this verification.
