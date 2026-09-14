# Existing Gordon local handshake

CorePilot remains the business front door and CommandCore remains the canonical
CRM. `corepilot_gordon.py` is a thin optional connection to Gordon's existing
`app/local_adapter.py`; it contains no Gordon runner, CRM copy, task queue or
approval store. Staff routing and owner approvals retain their existing services.

The verified local checkout is `C:\Users\msb75\CodingBot\workspace\bot_dev`,
at `6f87bd47f722ac9c50e02e2a715f0c3296af940b`. The previously supplied `bot\_dev`
path does not exist. The checkout is read in place; never copy or rebuild it.

An explicitly configured local caller constructs `existing_adapter(checkout,
inspection_root, journal)`, wraps it in `GordonConnection`, and supplies that
connection plus a `GordonJob` to the existing `run_corepilot` function. The
production page does not construct a connection. Without an injected connection
and identity, technical routing returns a preparation message and executes nothing.

The host must retain the same idempotency and correlation UUIDs across retries.
Do not regenerate identity on page rerenders or after an uncertain outcome.
Gordon allocates job IDs and uses its existing locked, durable journal to reject
duplicates, including after restart. That journal is technical audit evidence,
not another canonical task or business-data store. It must remain outside the
inspection root, in an explicitly approved local output directory. This milestone
uses isolated synthetic inspection roots and journals only.

Only fixed source-file reads are sent, one step per job with a ten-second bound.
Prompts and canonical records cannot select roots, journals, paths or commands.
Returned `gordon_outcome` carries accepted/rejected, job ID, status, result/error,
actions attempted, approvals required, cost and audit/correlation information.
CommandCore validates the envelope and correlation before returning it. Gordon's
own policy, timeout worker, approval rejection and duplicate controls are reused.
Neither naming Shawn/Sabrina nor claiming approval grants execution authority.
Consequential jobs are non-resumable rejections in the existing local protocol.

Technical intent supports integration troubleshooting, connector health checks,
automation diagnostics, system diagnostics and technical maintenance inspection.
Mixed staff/technical work requires clarification. Normal business work stays
with its existing staff specialist; universal staff backup does not replace Gordon.
An inspection returns metadata only: it does not establish remote connector
health or perform repairs. There is no remote status polling API in this synchronous
adapter; terminal status comes back from submit, correlated to its existing journal.

## Verification

- Offline routing/contract tests: `tests/test_corepilot_gordon.py`, alongside
  existing staff, orchestrator and page tests in the unchanged business simulator.
- Real adapter conformance: set `GORDON_CHECKOUT` to the verified checkout and run
  `.venv\Scripts\python.exe -B -m pytest scripts/check_gordon_handshake.py -p no:cacheprovider --basetemp <new-isolated-output>`.
  The tests load original Gordon code in place and inspect fictional source files.
  Use a fresh output directory; pytest basetemp is disposable test output only.
- Live-backed checks use canonical list/download operations and local page code;
  Gordon still receives only synthetic local inspection requests, never CRM data.
- The full simulator retains its production-file/network/subprocess barriers.
  It uses a fake Gordon transport; real Gordon worker tests run separately because
  the simulator deliberately forbids external checkout reads and child processes.

All live connection, deployment, communications, business writes, marketing,
spending and migration remain outside this local handshake authorization.

## Clean prerequisite port from main

Prepared on `codex/gordon-prerequisite-clean` from
`9de1e5165143dc91f169da98d7fe8e64dcdc2afa`. The verified historical source is
`c0fd65a`, not `cefd65a`; the protected caller commit is
`0e59ac8f787782ac30c75884cd25227d95d36837`.

The adapter bridge, handshake script and offline Gordon tests retain that source.
Only the optional Gordon parameters, early Gordon/staff read-routing hook, result
field and parameter forwarding were applied to main's conversation/orchestrator.
Unrelated conversation features and historical context were not ported.

Staff routing comes from `3c77ca1` (which incorporates `7de76c9`). The helper module
contains only `configured_members`, `resolve_member`, `work_for`, `route_function`
and `requested_functions`. No storage client, schema/provisioning, budget executor,
approval writer or live roster is included. Synthetic profile fixtures use plain
mappings; unrelated provisioning, delegation/budget and page tests were excluded.
Main's action classes, CorePilot framework, production page and existing lock remain
unchanged. Production does not instantiate Gordon or load live staff through this
port. No caller, repair/build support or activation is included.

The source conversation patch expected later property/staff context absent on main;
it was manually applied at main's existing answer entry. The orchestrator port is
only three changed lines plus its new result field. A local Windows text-decoding
artifact was corrected before final verification; unrelated text matches main.
No whole historical commit or recovery document was copied.

### Prerequisite verification

Initial selected suite: 165 PASS / 0 FAIL. Final broader suite: 205 PASS / 0 FAIL,
exit 0, including all 20 real-Gordon handshake cases and every `test_corepilot*.py`
module on this clean branch plus selected synthetic staff coverage. Selections
 overlap; do not add totals. Real adapter remains at audited commit
`6f87bd47f722ac9c50e02e2a715f0c3296af940b` and is loaded in place.

Final harness rejected network connections, credential files, original source and
business-data access; zero such attempts occurred. Only read-only installed-package
`.egg-info` metadata probes were permitted alongside the shared Python environment.
Initial strict harness attempts stopped optional plugin discovery (one collection
error) or reported blocked packaging metadata despite 205 test assertions passing;
these were harness configuration failures, not clean guarded passes. Optional
Pydantic plugin discovery was disabled, and the read-only package metadata exception
was narrowly scoped before the successful final run. No secrets or live records
were used. Gordon workers retain their existing reduced environment/network block.

Final output: `C:/Users/msb75/AppData/Local/Temp/gordon-prerequisite-final-pass-lly4v5r5`.
Repository-wide Ruff PASS; git diff --check PASS; additional new-file whitespace
check PASS with Windows CRLF handling. Runtime is Python 3.13.15 versus target 3.12.
Original recovery-document hashes and the protected caller commit remain unchanged.
All ten prerequisite paths remain uncommitted in the new worktree. No activation,
repair/build capability, push, merge, deployment or business write was performed.
