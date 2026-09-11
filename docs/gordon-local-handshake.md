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
