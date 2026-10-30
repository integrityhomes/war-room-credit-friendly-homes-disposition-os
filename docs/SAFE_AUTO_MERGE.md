# Safe auto-merge

Routine, low-risk pull requests can merge automatically after required checks pass when they carry the `safe-auto-merge` label.

## How it works

1. An owner (or trusted maintainer) adds the `safe-auto-merge` label to a non-draft PR targeting `main`.
2. The `CommandCore Safe Auto-Merge` workflow (`.github/workflows/commandcore-safe-auto-merge.yml`) runs on `pull_request_target` events.
3. It checks out the **base** branch only (never PR head code) and classifies changed paths with `scripts/safe_auto_merge_check.py`.
4. If any changed path is sensitive (secrets/auth, workflows, migrations, contracts/money/compliance, `AGENTS.md`, etc. — see the script’s list and `AGENTS.md`), the workflow removes the label, comments that owner approval is required, and disables auto-merge.
5. Otherwise it enables squash auto-merge pinned to the current head SHA (`gh pr merge --auto --squash --match-head-commit`).

Fork PRs and draft PRs are skipped.

## Branch protection (required)

Auto-merge only completes when GitHub branch protection on `main` requires the checks you care about (at minimum the `CI` workflow from `.github/workflows/ci.yml`). Enable **Allow auto-merge** in repository settings, keep required status checks on, and do not bypass protection for consequential changes.

## What not to label

Do not add `safe-auto-merge` to PRs that touch credentials, auth, storage secrets, database/Supabase migrations, GitHub Actions, product vision / agent rules, contracts, payments, banking, compliance, legal/signing, or offer-engine code. Those need explicit owner approval per `AGENTS.md`.
