# Coordinated bounded synthetic caller interface

Developed only on `codex/gordon-bounded-repair-build` with the separate Gordon
`codex/gordon-bounded-repair-adapter` worktree. Neither audited/original checkout
is modified. Nothing is committed, pushed, merged, deployed, or production-enabled.

`SyntheticGordonCaller.create_bounded` creates the existing fictional inspection
workspace plus one `synthetic_change.py` fixture. A trusted host-injected synthetic
approval mapping is mandatory for this mode. Legacy creation and inspect behavior
remain available without that mapping. Production remains disabled.

`enqueue_operation` accepts only inspect, propose_change, apply_change,
run_validation and report_result. It records a fixed bounded request inside the
existing caller.json job row. Stable IDs use the existing namespace and UUID5 scheme;
operation-specific canonical-shaped synthetic task references prevent job collisions.
Changing a request or approval reference under the same job ID fails closed.

Dispatch remains caller -> GordonConnection -> existing_adapter -> existing
LocalGordonAdapter. No direct file edit or validation executor is added to CommandCore.
The approval grant is never taken from a caller request or embedded in the journal;
only its safe evidence reference is persisted. Gordon verifies job/workspace/scope,
operation, fixture hashes and expiry against the injected test authority. Real owner
approval verification is not implemented or implied by these synthetic grants.

Only the fixed fictional change VALUE=1 to VALUE=2 is executable. The only validation
IDs are python_syntax and expected_value; both are static checks in Gordon, with no
shell or workspace-code execution. This is a narrow protocol proof, not a general
repair/build engine. Arbitrary requested scope, command IDs and operations fail closed.

The existing locked, atomic caller snapshot persists dispatch intent before adapter
invocation, receipt before finalization and the structured result. After a restart,
queued work can retain its identity, received results can finalize, completed or
failed work cannot redispatch, approvals stay blocked, and interrupted dispatched
work becomes blocked_uncertain. Never replay an uncertain mutation. No automatic
rollback or approval-resume endpoint exists. The adapter journal supplies a second
duplicate barrier and historical result evidence.

Run scripts/check_gordon_bounded.py, scripts/check_gordon_caller.py and
scripts/check_gordon_handshake.py against the isolated Gordon worktree, plus the
CorePilot/staff regression suite. All fixtures and journals are disposable temporary
outputs. Existing caller I/O guards forbid parent network, credential and original
project reads; subprocess crash fixtures have reduced environments and fixed code.

Before any real end-to-end trial: review a canonical owner-approval authority, a
trusted sandbox/command policy for running actual code, general scoped patch formats,
and manual reconciliation/rollback for uncertain mutations. Current tests establish
only the fixed synthetic protocol. Windows power-loss durability and distributed
writers remain unproven. Runtime is Python 3.13.15, not project target 3.12.

## Verification for this uncommitted phase

- Coordinated CommandCore suite: 241 passed / 0 failed (18 bounded-interface,
  18 existing caller, 20 existing handshake, 185 CorePilot/staff tests).
- Gordon suite: 101 passed / 0 failed / 2 explicitly deselected as dependency-blocked
  (30 new bounded, 45 existing adapter, 8 execution-safety, 18 Git-safety cases).
- The two excluded existing tests failed import in earlier runs because `openai`
  is absent: test_real_planner_client_never_calls_paid_api and
  test_read_and_list_are_not_behavioral_verification. They are NOT verified passes.
- CommandCore repository Ruff PASS. Gordon repository Ruff reports 142 existing
  findings; its modified adapter has the same 8 lint findings as the baseline and
  the new test file has zero. No unrelated lint cleanup or dependency install.
- git diff --check PASS in both repositories. No commit/push/PR/merge/deployment.
- Preservation: all 217 readable audited Gordon files and 1,563 readable original
  CommandCore files match pre-edit SHA256 hashes, including both recovery docs.
  Permission-denied pre-existing cache directories were not hashable and remain
  outside the byte-for-byte verification claim. Audited HEAD remains 6f87bd47;
  original CommandCore HEAD and old caller branch remain unchanged.
