# AGENTS.md

## Mandatory session recovery
- At the start of every fresh conversation in this repository, including when the entire request is "Resume CommandCore", read `AGENTS.md`, then `docs/SESSION_STATE.md`, then `docs/NEXT_TASK.md` before any other repository operation or task execution. Reading these control files is the first operation.
- Then inspect local git status and HEAD, reconcile them with the recorded state, and preserve all existing committed, uncommitted, untracked, ignored, questionnaire, and profile work. Never reset, clean, stash, undo, or overwrite existing verified work to resume.
- If a control file is missing or the evidence conflicts, stop dependent actions and report the gap. Do not reconstruct approvals or private profile details from assumptions.
- "Resume CommandCore" authorizes recovery and safe local inspection only. It is not activation, deployment, push, spending, migration, or business-data-write approval. Follow the exact next task only within its explicit approval gate.
- Before ending substantive work, update both state documents with evidence, outstanding local changes, approvals, unresolved issues, and the exact next task. Distinguish historical/user-reported verification from checks run in the current session. Never place private records or secret values in these files.

## Canonical architecture and approval boundaries
- Extend the existing architecture; do not duplicate it. Maintain one canonical CRM/data architecture and reuse existing services, IDs, adapters, approval records, and preservation contracts.
- Staff belong in the existing private `commandcore-team-registry` bucket under `members/`, using the existing registry service and `src/cfh_disposition/staff_profiles.py`. A preparation bundle is evidence, not a second operational roster. Preserve questionnaires, provenance, existing profiles, roles, and unrelated member fields.
- Shawn and Sabrina retain owner-level approval authority. Staff roles, operational delegation, universal backup, and bot-generated plans never transfer owner approval authority.
- No schema migration, spending, or consequential deployment/action without explicit required owner approval. Never infer approval from a test PASS, a prepared profile, or a previous unrelated deployment. This six-person activation specifically requires Shawn's explicit activation approval.
- Production safety: default to local, read-only inspection and isolated simulation. Do not push, deploy, activate staff, change business data, send communications, or run migrations as part of recovery. Obtain the applicable approval before consequential execution; verify preservation and exact scope before authorized writes.
- Keep Grant and Fort deferred until separately approved. Do not invent missing identity, capacity, authority, questionnaire answers, budgets, or approval limits.

## Simulator and concurrency requirements
- Use the existing offline business simulator (`scripts/run_business_simulator.py`) and synthetic fixtures for business/compliance changes; preserve its credential-free environment, network/production-file barriers, fake adapters, and isolated outputs. See `docs/business-simulator.md` and the simulator coverage documents.
- Run relevant pytest and Ruff checks; report failures, blocked runs, skips, runtime mismatches, and coverage limits honestly. A simulator PASS never authorizes production action. Review substantive business-rule failures rather than silently changing expected behavior.
- Preserve current single-worker operation for current-inventory import and internal task revisions. Existing source locks, deterministic create-only paths, and process-local revision locks are not proof of distributed concurrency safety. Do not enable parallel/distributed writers or weaken locks without separately reviewed safeguards and required approval.
- Recovery testing must read the three control files in order, recover the milestone and next task, and confirm that absent explicit Shawn approval the decision is HOLD. Use local reads only; do not call production adapters or activate a prepared profile to test recovery.

## Mission
Build a focused owner-finance disposition operating system for Credit Friendly Homes. Do not add wholesale disposition features to this repository.

## Public repository safety
- Assume every committed file is visible to competitors and the public.
- Never commit credentials, tokens, passwords, API keys, buyer records, applications, or real property records.
- Never commit proprietary scoring weights or internal approval rules that would materially expose the business advantage.
- Use fictional sample data only.
- Store production secrets in Streamlit Secrets or the hosting provider.

## Product rules
- Property facts must be verified before any content is generated or published.
- AI must never invent price, payment, down payment, property condition, repairs, bedrooms, bathrooms, availability, or approval terms.
- Never promise approval or imply that everyone qualifies.
- Preserve Fair Housing compliance and communication consent.
- Facebook Marketplace remains assisted/manual publication; do not build unauthorized browser automation.
- Paid advertising always requires budget approval.
- Sold and pending properties must not launch active campaigns.
- Google Business Profile is optional and not required for launch.

## Engineering rules
- Use Python 3.12, Streamlit, Pydantic, pytest, and Ruff.
- Add tests for important business and compliance logic.
- Keep pull requests small and focused.
- Routine CommandCore pull requests may merge automatically only after all required CI checks pass, the pull request is conflict-free and mergeable, and the verified head SHA has not changed.
- Never auto-merge changes involving credentials or secrets, destructive data changes, legal or compliance decisions, spending or money movement, bank-information changes, signing or binding agreements, major architecture changes, or other consequential owner approvals. Stop for explicit owner approval on those items.
- Do not bypass branch protection, required checks, owner approval gates, or repository safety controls in order to merge.
- Run linting and tests before opening a pull request whenever tools allow; open routine PRs as non-draft when they are ready for CI.
- Use provider adapters so WordPress, OpenAI, REI BlackBook, Supabase, and social integrations can be replaced.
