# CommandCore business simulator

Open **Business Simulator** inside the existing application, or run
`.venv\Scripts\python.exe scripts/run_business_simulator.py` locally. This extends
the existing `cfh_disposition.harness` package and pytest suite. There is no
production-mode switch, new service, dependency installation, or live scheduler.

The launcher passes a minimal environment without production credentials to a
separate Python process. An irreversible audit hook blocks network/DNS, external
process execution, production writes, production runtime/secret reads, and unsafe
filesystem links. A blocked action terminates the complete child immediately.
The only sockets allowed are Python's authenticated self-connected Windows
asyncio wakeup pipe. External IPv6 capability probing is disabled. Writes and
temporary links are confined to one isolated run directory. The boundary assumes
trusted repository Python; it is not a sandbox for hostile native extensions.

The live Streamlit process never receives these hooks. It can only launch the
fixed offline runner and display its results. Simulation datasets use fictional
addresses, owners, communications and workers. Header-layout fixtures contain
column names only, without real section names, addresses, or access values.

Real parser, identity, current/history, field interpretation, detector, aging,
CorePilot, task, communications, approval, deal and marketing functions execute
with fake external I/O. Existing AppTest scenarios exercise the real Command Bot
page. The synthetic clock advances dates without real-time waiting. The new
29-property scenario uses the real current-candidate rules and a fake create-only
canonical transport; it must not be confused with an approved live importer.

The current-inventory executor now has a separate real-implementation scenario:
snapshot approval, full canonical re-read under the existing source lock, atomic
create-only property upload, and exact read-back verification all execute with a
fake canonical bucket. The implementation has no live UI or scheduler entry point.
It never writes marketing checkpoints; the observer derives prospective aging
from a verified subsequent source observation. Live import remains unapproved.

See `simulator-coverage-review.md` for the explicit classification of the original
60 unexercised modules. Remaining cross-process coverage is a real limitation:
property imports use an OS source lock plus deterministic create-only paths;
internal task creation also uses deterministic create-only storage; task revisions
use a process-local lock. End-to-end simultaneous worker behavior has not been
proved by the isolated runner. Do not infer distributed concurrency guarantees.

Results remain in ignored `.commandcore-runtime/business-simulator/run-*` folders.
PASS means scenario assertions succeeded, not that every module branch is tested.
The coverage matrix inventories every Python service/module and page route and
records actual execution during scenarios. Unexercised modules are WARNING.
One existing test launching an unguarded child process is explicitly skipped;
coverage of cross-process locking requires a guarded child adapter. Skips and
business failures remain visible rather than being changed to force a pass.

Isolation self-tests are available through `--probe network`,
`--probe production-file`, and `--probe production-adapter`. They deliberately
trigger the wall and must produce a blocked-operation result, without reaching
a live endpoint or creating the forbidden file. Probe runs are separate from
business-scenario results and hidden from the normal results selector.

Do not repair substantive business rules automatically after a FAIL. Review the
scenario, expected behavior, actual assertion, affected modules and next step
before authorizing changes. No live import or marketing checkpoint creation is
authorized by a simulator PASS.
