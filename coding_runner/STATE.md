# Coding Runner State

## Architecture
- Standalone Phase 1 Python runner under `coding_runner/`.
- No imports from CommandCore operational code.
- Stable version remains untouched while development occurs on feature branches/workspaces.

## Files
- `README.md` — Phase 1 purpose and safety boundary.
- `STATE.md` — this resumable checkpoint.
- `.env.example` — configuration names only; no secrets.
- `src/runner/` — policy, workspace, Git, report, and CLI modules.
- `tests/` — Phase 1 safety tests.

## How to start
Docker status on the Windows host has not yet been verified. Do not assume Docker. Local Python/venv remains the fallback.

## Last test
Pending CI for this foundation branch.

## Next step
Finish the Phase 1 skeleton, run repository CI, then verify Docker on the Windows host before adding container configuration.

## Uncommitted work
GitHub connector writes create feature-branch commits directly. No changes are being made to `main` until owner-approved PR merge.

## Needs owner approval
- Merge to `main`.
- Any future change that weakens policy/permission controls.
- Production deployment, credentials, spending, paid services, privilege changes, or public exposure.
