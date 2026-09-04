# CommandCore trusted local verification

`scripts/verify_commandcore.py` bundles routine local verification after an approved build plan. It does not implement, stage, commit, deploy, connect providers, or perform remote Git operations.

## Approval flow

The normal routine build flow is:

1. Approve the scoped build plan.
2. Approve implementation and one trusted local verification run.
3. After a PASS report and Codex diff review, approve one exact-file local commit.

## Example

Run from the CommandCore repository with every changed file and focused/regression test named explicitly:

```powershell
.\.venv\Scripts\python.exe scripts\verify_commandcore.py `
  --changed scripts/verify_commandcore.py `
  --changed tests/test_verify_commandcore.py `
  --changed docs/COMMANDCORE_VERIFICATION.md `
  --focused tests/test_verify_commandcore.py `
  --regression tests/test_commandcore_harness.py `
  --full
```

The runner verifies the repository root, refuses path traversal and wildcards, runs focused and selected regression tests, optionally runs the full suite, runs repository-wide Ruff, checks the scoped files for likely credential values and whitespace errors, and invokes the installed CodingBot trusted Docker runtime for a network-disabled read-only focused test run.

The trusted dependency image must already exist. The runner will not download dependencies or build an image because that could require network access.

## Safety boundary

- CommandCore is mounted read-only in Docker.
- Docker networking is disabled.
- The container is read-only, non-root, capability-dropped, resource-limited, and receives no Docker socket.
- Proxy variables are cleared for local verification processes.
- No secrets or live-provider settings are read or passed.
- Only exact, project-relative paths are accepted.
- Verification stops after the first failed stage.
- No Git staging, commit, push, fetch, pull, merge, rebase, reset, or checkout operation exists in the runner.
- Unrelated dirty files are reported and preserved.
- Cleanup is restricted to a randomly named directory under `.commandcore-verification` with an exact matching ownership marker created by the same run.

## Result

The runner prints a JSON PASS/FAIL report containing the exact declared changed files, unrelated dirty files, every completed step, the first failed step, cleanup result, final worktree state, remote Git operations (`NONE`), and external-service spend (`$0`).

Commands that remain outside the bundle are trusted-image installation or dependency download, final exact-file staging/commit, live integrations, deployment, schema migration, secret changes, and every consequential external action.
