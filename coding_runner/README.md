# Private Coding Runner — Phase 1

This directory is a self-contained, portable Dev-team coding runner foundation. It is intentionally separate from CommandCore operations and has no dependency on Command Center, Supabase CRM, email, SMS, signing, advertising, payments, or deployment services.

## Phase 1 goal

Safely work inside one approved repository workspace: inspect, plan, edit on a feature branch, run tests, report results, and stop for owner approval before commit/push/merge/deploy.

## Safety model

- Workspace paths are allowlisted and must resolve inside the configured workspace root.
- `main` and `master` are protected branches and cannot be used for development edits.
- Runner-control files are protected from autonomous edits unless owner approval is explicitly provided by the caller.
- Secrets come from environment variables only.
- Production CRM writes, outbound communications, signing, spending, paid services, deployment, and privilege escalation are out of scope.
- The stable runner must never be overwritten first. Future upgrades to the runner itself must use an isolated branch/workspace and preserve rollback.

## Portability

The runner uses relative/configurable paths and standard Python. Docker support will be added only after Docker is verified on the first Windows host. A local virtual-environment fallback will remain supported.

## Current status

This Phase 1 foundation provides policy, workspace-boundary, Git branch guards, reporting, and checkpoint structure. It does not yet execute arbitrary shell commands or autonomously edit a real target repository.
