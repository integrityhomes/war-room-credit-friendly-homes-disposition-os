# Local Meta compliance audit and implementation — 2026-09-14

Scope: existing CommandCore only; local implementation and isolated synthetic tests. No Facebook browser automation, account switch, publication, messaging, ads, spending, deployment, push or merge. Marketplace access restoration is owner-reported pending; it was not checked live.

## Audit before implementation

Entry: `main`, HEAD `fe7370391b680b431c0e47c7e59d7eb7da4c8e4d`, ahead 13 of the local tracking reference. Only `docs/SESSION_STATE.md` and `docs/NEXT_TASK.md` were modified; their recovery entries were preserved. Git warned that two old ignored test directories were inaccessible. No private evidence, profiles, questionnaires or business data were changed.

Existing authoritative protection is `meta_marketplace_policy.py`, backed by `listing_compliance.py`, plus channel-specific fact/template validation. Existing rules cover deceptive approval/credit claims, unsafe payments and fees, financial fraud, sensitive-data requests, discriminatory housing language, unsupported condition/neighborhood claims and required disclosures. Marketplace has on-platform contact copy, no public links, exact terms, internal-price handling and monthly/duplicate controls. AI generation locks Facebook fields to deterministic templates. Group queue/assignment logic preserves group cooldowns and current-property checks. Paid copy review and campaign approval records already exist. Operational failure logging and the existing offline simulator remain in use.

Inspected the requested modules, tests and call sites: Marketplace/calendar/UI, Groups/queue/variations/assignments/failure scan, AI campaign, paid traffic, campaign launch, automatic launch, go-live connections and operational failures. Expanded the audit to social publish handoff, cadence refresh and property shutdown/resume because they contain outbound execution paths. Connection-test and safe-payload helpers carry explicit nonpublication instructions. The current canonical TypeScript receiver routes/queues work and has no Meta publication adapter; it was not changed or deployed. Marketing optimizer's HTTP call is to its existing optional AI drafting provider, not a Meta publisher.

## What changed

- Extended `meta_marketplace_policy.review_meta_action`, without creating a competing policy engine, registry or CRM. Its immutable result has PASS/WARNING/BLOCK, finding codes/reasons/corrective actions, channel/action, content hash, canonical property ID when supplied, version, timestamp, required asset states, evidence time, Commerce state, Meta errors and human-approval requirement.
- Central review reuses existing content rules. Paid internal approval instructions are no longer scanned as public copy; the actual creative remains checked. Shared fact checking now accepts both existing exact address formats and legacy numeric strings without changing their numeric value.
- Versioned local safety profile requires HOUSING, age 18 through 65+, All genders. No detailed/protected-class targeting, lookalikes, exclusions, ZIP targeting or other unreviewed audience fields are accepted. Codes 2909037, 2909036 and 2909035 block until corrected; other unresolved provider errors also fail closed.
- Required asset dependencies are channel-specific. Missing, manual-only, stale (over 24 hours), future or restricted health cannot permit a live action. Extra required assets are supported. Restriction-bypass intent blocks even preparation. No account substitution is implemented.
- Required Commerce must be verified working. Deprecated/stale/disabled/unknown required Commerce and stale Offsite Checkout block publication. Explicitly unnecessary Commerce does not block and does not require a Shop.
- Marketplace has an explicit recovery hold, including the UI's new-publication record action. Copy can be prepared with warnings; no publication is claimed. The hold cannot be cleared through payload flags or claimed healthy status.
- Automatic launch rechecks and removes Meta channels at transport time, even from forged/stale payloads. Cadence refresh and Instagram handoff block before network I/O. Resume excludes Meta instructions and keeps those channels paused; shutdown remains available. Healthy non-Meta dispatch rows are preserved. No verified health provider is wired to these transports, so no live Meta publishing is enabled.
- Group public copy no longer receives external tracking URLs through launch helpers, variations or refresh. Attribution links remain in existing internal records. UI labels explicitly forbid public pasting, and legacy saved assignments containing links are flagged for regeneration without overwriting them. Historical posting records and cooldowns remain intact.
- Each gate call emits a structured application log without raw copy, tokens or provider response text. Existing paid compliance records and new assignment records carry the decision; Marketplace review objects and local launch plans expose it. Content hashes correlate decisions with the existing package/record. Deployment log retention is not verified by local tests; no new remote audit store was created.

## Conflicts and intentionally conservative choices

AI validation prohibited Group URLs while variations, launch helpers, refresh tests and UI guidance required/endorsed them. All affected current public-copy paths now use the existing conservative no-link rule; internal attribution is retained. Old historical audit documents remain historical evidence. Meta paid notes now identify Shawn/Sabrina's authority rather than implying a manager can approve spending.

The exact 18–65+ settings, error codes and Marketplace recovery hold come from the owner's requested local safety profile. They are not presented as a complete, eternally current interpretation of Meta policy. Meta's official [housing ads fairness announcement](https://about.fb.com/news/2022/06/expanding-our-work-on-ads-fairness/) confirms restrictions on age, gender and ZIP targeting. The current detailed Help Center page redirected to login and the anti-circumvention policy page could not be retrieved; their full current text was not independently verified. No Facebook authentication was attempted. The reviewable constants and policy version must be revisited before any future activation.

## Verification and remaining limits

See the current recovery documents for exact final run paths and counts. Tests use only the existing credential-free offline business simulator, fake transports and synthetic fixtures. Initial runs exposed address-format/legacy-number integration regressions, obsolete public-Group-link expectations and a new resume test fixture that incorrectly started already-live; each was reviewed and corrected. No substantive safety rule was relaxed to force a pass.

This is local protection, not proof of current remote account health, full Meta-policy certification, live channel readiness or deployment. Current Python is 3.13.15 versus the repository's 3.12 target. The existing simulator's controlled cross-process coverage limitation and single-worker requirements remain. No automatic approval, spending, distributed writer, staff activation or profile changes were added. Future live Meta work requires current authorized evidence, applicable owner approval and reviewed transport integration; a synthetic PASS grants no authority.

The first full run also exposed an existing attribution fixture-registration dependency on collection order: all eight Marketplace attribution cases passed alone but failed after the marketing attribution module was collected. A two-file reproduction confirmed it. Explicitly importing the two existing fixtures resolves the issue (50/50 pass) while preserving every attribution assertion. The final full-suite rerun is recorded in the recovery documents.

## Final test evidence

| Run | Result |
| --- | --- |
| Targeted Facebook/Meta/marketing `run-3mwzs_fi` | 179 PASS, 0 FAIL |
| Attribution fixture-order reproduction `run-6f0tr5ae` | 42 PASS, 8 setup FAIL |
| Same attribution selection after explicit fixture imports `run-5ru2wlgj` | 50 PASS, 0 FAIL |
| First full simulator `run-mzuhfxz7` | 1,912 PASS, 1 controlled cross-process WARNING, 8 fixture-setup FAIL |
| Full rerun `run-t1tygb1a` | 1,919 PASS, 1 controlled cross-process WARNING, 1 AppTest timeout FAIL |
| Unchanged UI module isolated `run-bkybxkcx` | 71 PASS, 0 FAIL; original 30-second timeout retained |
| Ruff over src/cfh_disposition and tests; git diff --check | PASS |

All simulator runs report production access attempted false. The lone timeout was in the unrelated canonical-task work-view AppTest; it passes in isolation and passed in the first full run. No clean full-suite PASS is claimed. No timeout increase or business-rule relaxation was made. The user should review this timing limitation along with the local diff before any separately authorized release. All edits remain uncommitted; no push or merge.

## Fresh owner-requested final verification — 2026-09-14

No code or test changes were made during this verification. Both runs used `.venv\Scripts\python.exe scripts/run_business_simulator.py --tests` followed by the exact selections below. All selected cases passed, with zero warnings/skips, zero failures and production access attempted false. The second selection includes the first.

Focused run `run-lzbn156s`: **70 PASS**.

```text
tests/test_meta_safety_gate.py
tests/test_meta_paid_ad_compliance.py
tests/test_marketplace.py
tests/test_facebook_group_variations.py
```

Broader run `run-vm357u_9`: **292 PASS**.

```text
tests/test_meta_safety_gate.py
tests/test_meta_paid_ad_compliance.py
tests/test_marketplace.py
tests/test_facebook_group_variations.py
tests/test_listing_compliance.py
tests/test_marketplace_calendar.py
tests/test_facebook_groups.py
tests/test_facebook_group_queue.py
tests/test_facebook_assignments.py
tests/test_facebook_group_import.py
tests/test_facebook_posting_center_consolidation.py
tests/test_ai_campaign.py
tests/test_paid_traffic_channels.py
tests/test_campaign_launch.py
tests/test_automatic_launch.py
tests/test_operational_failures.py
tests/test_social_publish_handoff.py
tests/test_marketing_attribution.py
tests/test_marketplace_inquiry_attribution.py
tests/test_campaign_cadence.py
tests/test_property_shutdown.py
tests/test_go_live_connections.py
tests/test_go_live_connections_truth.py
tests/test_paid_ads_planning_usability.py
tests/test_commandcore_marketing_home_usability.py
tests/test_commandcore_marketing_setup_status_usability.py
tests/test_property_marketing_eligibility.py
tests/test_property_marketing_highlights.py
tests/test_commandcore_meta_lead_adapter.py
tests/test_commandcore_meta_lead_intake.py
```

Additional checks: `.venv\Scripts\python.exe -m ruff check src/cfh_disposition tests --output-format concise` and `git diff --check` both PASS. No new failures required fixes. Prior implementation and full-suite results above remain historical; no fresh full-suite pass is claimed. Only verification records were updated. All application/test edits remain uncommitted, with no live action, push, merge or deployment.
