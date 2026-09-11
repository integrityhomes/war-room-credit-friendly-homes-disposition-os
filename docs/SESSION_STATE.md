# CommandCore session state

Recorded: 2026-09-11 (America/New_York). This is a local recovery checkpoint, not production authorization.

## Current milestone
Property foundation complete. Command Bot/CorePilot foundation complete. Six staff profiles (Carlos, Chase, Mars, Gabe, Gerald, Russ) prepared and tested, awaiting separate Shawn-approved activation. Grant and Fort deferred. Team-registry compatibility/preservation fix deployed; staff activation has NOT occurred.

## Verified completed work and deployed components
- Owner's session handoff reports the foundations complete, compatibility fix successfully deployed, no database migration required, live preservation verification passed, and 107 relevant tests passed in the previous session. The 107-test result is historical and was not reproduced here.
- Local HEAD contains the staff profile/routing implementation, Command Bot changes, tests, and registry preservation fix. The latest checkpoint is `7de76c9 WIP checkpoint before full restart - preserve staff profile work`.
- Saved private deployment evidence (`.commandcore-runtime/team-registry-deployment-verification.json`) records live preservation PASS, partial-profile and availability/workload preservation, invalid-profile rejection, test-record removal, byte-identical preexisting records, and zero real profiles activated. These are saved results, not a fresh live check.
- Private preparation bundle exists with all six profiles and `PREPARED_NOT_IMPORTED` status. Existing questionnaires and profile work remain in place; nothing was imported or edited. No production connection, deployment, push, activation, business-data change, or migration was performed in this recovery session.

## Repository/git state and uncommitted work
- Repository: `C:\Users\msb75\CodingBot\workspace\CommandCore`.
- Branch: `main`; HEAD: `7de76c90e5482961f1f3afd85c23233dc471a355`.
- Local tracking reference: `origin/main`; branch is ahead by four commits. No fetch was performed; this does not establish current remote state.
- Entry inspection showed no tracked modifications, staged changes, or visible untracked files. Staff work is checkpointed, not lost. Git could not inspect `.phase5c-pytest-temp/` and `.test-tmp/phase5a-full/` because access was denied; do not infer their contents are empty.
- Recovery-session changes: modified `AGENTS.md`; new `docs/SESSION_STATE.md` and `docs/NEXT_TASK.md`. All remain uncommitted; no existing application files were changed.
- Ignored `.commandcore-runtime/` holds private evidence and existing work; preserve it. Several old test/runtime directories are unreadable. No cleanup, stash, reset, permission repair, or overwrite was performed.

## Simulator/test state
- Existing simulator and coverage records: `docs/business-simulator.md`, `docs/simulator-coverage-review.md`, `docs/simulator-surface-inventory.md`. Distributed/cross-process behavior is not fully proved; current single-worker restrictions remain.
- Current local registry-handler check: `node scripts/test_team_registry.mjs` PASS, using synthetic in-memory transports, with zero external requests.
- Attempted isolated regression selection: `tests/test_staff_profiles.py`, `tests/test_command_bot_completion.py`, `tests/test_corepilot_current_foundation.py`. The launcher was blocked before pytest by PermissionError writing `selection.json` in new ignored directory `.commandcore-runtime/business-simulator/run-lfw8lfh3/`. No regression PASS is claimed and no production fallback was used. The incomplete run directory is preserved.
- Local `.venv` reports Python 3.13.15; standing engineering target remains Python 3.12. No environment changes were made.
- Recovery validation PASS: a fresh local Python process read the three control files in the prescribed order and checked the recovery instruction, exact next task, explicit HOLD gate, six role titles against the private bundle, and retention of all original standing rules. SHA-256 comparisons confirmed the private preparation bundle and saved deployment evidence unchanged. Git confirmed application files and the index unchanged; `git diff --check` passed. This was a read-only recovery-contract dry run, not an independent Codex conversation or live production test. Future Codex recovery relies on following the root `AGENTS.md` instructions.

## Pending approvals and unresolved issues
- Shawn's explicit activation approval is required for the exact six prepared profiles. No such approval is implied by this document, the saved deployment evidence, or a future "Resume CommandCore" request.
- No approval exists in this recovery session for push, deployment, business-data writes, migrations, or spending. Consequential actions retain applicable owner gates.
- Private profile unknowns remain unresolved: blank/N/A answers, capacity/limits, some manager references, secure buyer-ID workflow, and system-of-record split. Preserve evidence and verify before dependent actions. Detailed private rules remain outside tracked documentation.
- Simulator output-directory permissions and the Python target mismatch remain unresolved. Saved live verification has not been rechecked against production in this session.

## Exact next task
Activate the six approved staff profiles in the existing canonical team registry, only after Shawn's explicit activation approval.

Read `docs/NEXT_TASK.md` for existing roles, source locations, preservation requirements, and the HOLD gate. A fresh session must first read `AGENTS.md`, this file, and `docs/NEXT_TASK.md`, then inspect local git state. Without Shawn's explicit approval, recover context and remain on HOLD.
