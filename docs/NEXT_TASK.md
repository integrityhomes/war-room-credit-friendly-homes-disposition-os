# CommandCore next task

## Exact next task
Activate the six approved staff profiles in the existing canonical team registry, only after Shawn's explicit activation approval.

## Approval gate
Status: HOLD — Shawn's explicit activation approval has NOT been given in this recovery session. Profile preparation/role approval is not activation approval. "Resume CommandCore" does not open this gate. Shawn and Sabrina retain owner-level authority; none of these six profiles grants owner approval authority. Grant and Fort remain deferred.

## Existing prepared roles and authority
These summaries come from the existing private preparation bundle. Preserve its full functions, handoffs, authority restrictions, source evidence, and questionnaires; these summaries do not replace or expand them.

| Staff | Prepared role | Existing delegated scope |
| --- | --- | --- |
| Carlos | Operations Manager / Integrator / Universal Staff Backup | Operations and backup across explicitly declared staff functions; routine work within approved rules; no transfer of owner authority. |
| Chase | Transaction Coordinator / CFD Specialist / Buyer Onboarding | Closing/title coordination, CFD preparation, onboarding, property administration; routine coordination using approved information. |
| Mars | Owner-Finance Buyer Lead and Follow-Up Specialist | Buyer follow-up/communication and showing coordination within verified facts, approved terms, consent and STOP rules. |
| Gabe | Acquisitions Lead | Acquisitions, seller communication, offer preparation within existing verified acquisition rules; no new wholesale disposition scope or binding authority. |
| Gerald | XLeads / CRM Data Operations / GHL Marketing Automation Specialist | Lead data operations, CRM automation, reporting and assignment; no implied sending or spending approval. |
| Russ | Social Media and Property Marketing Specialist | Property marketing, social inquiry triage and paid-ad management within approved rules; buyer follow-up follows verified handoffs; paid work requires a current owner-approved weekly cap. |

All six have `owner_approval_authority=false`; only Carlos has `universal_staff_backup=true`. Delegation checks in the current implementation permit preparation only and keep external execution disabled. Activation must not enable external executors, communications, spending, or owner powers.

## Preparation evidence and authorized execution boundaries
- Private local source: `.commandcore-runtime/staff-profile-preimport.json`, status `PREPARED_NOT_IMPORTED`. Its proposed `active=true` member fields are intended payload values, not evidence of live activation. Never import it merely to resume, and never commit it.
- Existing implementation: `src/cfh_disposition/staff_profiles.py` and `supabase/functions/commandcore-team-registry/index.ts`; canonical storage: `commandcore-team-registry/members/`. Use existing identity checks and preservation gates; no alternate roster, migration, blind overwrite, or upsert around create-only provisioning.
- After explicit Shawn approval, first re-read the approved private bundle and current registry, verify identities, complete source preservation, and the live compatibility contract. Confirm the exact six-person scope. If identities/profile contents differ, stop for review; preserve existing entries.
- Perform only the specifically approved registry operation, with one worker. Read back and verify the exact six profiles and unchanged preexisting records/questionnaires; repeated execution must not duplicate or overwrite members. Record evidence privately and update session state with a public-safe summary.
- Unknown answers, capacities, numeric limits, manager references, buyer-ID workflow, and system-of-record details remain unresolved as recorded in the private profiles. Do not silently fill them in. Any action dependent on those details stays blocked until verified.
- If the private source is unavailable in another checkout, stop activation and request the existing approved source through a private channel; do not fabricate replacement profiles.
