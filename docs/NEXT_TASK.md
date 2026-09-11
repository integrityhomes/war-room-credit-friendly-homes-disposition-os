# CommandCore next task

## Exact next task
Await Shawn's instruction for the recommended staff workflow readiness milestone: review workloads, handoffs, verified budget evidence, and unresolved profile details without assignments or external execution.

## Approval gate
Status: ACTIVATION COMPLETE — Shawn explicitly approved activation in this conversation on 2026-09-11. Carlos, Chase, Mars, Gabe, Gerald, and Russ were created and verified in the existing canonical registry at 13:27:16 UTC. All six profiles and questionnaires match their source exactly; repeat provisioning made no writes. Shawn and Sabrina retain owner-level authority; none of these six profiles grants owner approval authority. Grant and Fort remain deferred. "Resume CommandCore" authorizes recovery only and must not repeat this completed task or enable further consequential actions.

Status of subsequent read-only smoke: PASS. Live canonical reads and actual Team/Management and CorePilot pages were exercised through Streamlit AppTest with live read-only adapters; no browser session was available. Isolated normal-update simulation preserved all six complete profiles, and fresh live registry bytes remained unchanged. The user-authorized local checkpoint records these results; nothing was pushed or deployed. The recommended milestone above is a proposal, not authorization for new business actions.

## Existing prepared roles and authority
These summaries come from the existing private preparation bundle. Preserve its full functions, handoffs, authority restrictions, source evidence, and questionnaires; these summaries do not replace or expand them.

| Staff | Prepared role | Existing delegated scope |
| --- | --- | --- |
| Carlos | Operations Manager / Integrator / Universal Staff Backup | Operations and backup across explicitly declared staff functions; routine work within approved rules; no transfer of owner authority. |
| Chase | Transaction Coordinator / CFD Specialist / Buyer Onboarding | Existing transaction/title/wholesale closing coordination, CFD preparation, onboarding and property administration; routine coordination using approved information. This preserves an existing responsibility, not a new wholesale disposition feature. |
| Mars | Owner-Finance Buyer Lead and Follow-Up Specialist | Human buyer specialist partnered with Nevaeh; buyer follow-up/communication and showing coordination within verified facts, approved terms, consent and STOP rules. |
| Gabe | Acquisitions Lead | Agent, FSBO and off-market acquisitions; seller communication and offer/counteroffer preparation within existing verified acquisition rules; no new wholesale disposition scope or binding authority. |
| Gerald | XLeads / CRM Data Operations / GHL Marketing Automation Specialist | Original CRM/GHL workflows, campaigns, funnels, reporting and organization, plus XLeads intake, mapping, deduplication and assignment to verified acquisition staff; no implied sending or spending approval. |
| Russ | Social Media and Property Marketing Specialist | Paid/unpaid property marketing and social inquiry triage within approved rules; buyer follow-up follows verified handoffs; paid work requires current owner-approved weekly budget evidence and spend controls. |

All six have `owner_approval_authority=false`; only Carlos has `universal_staff_backup=true`. Delegation checks in the current implementation permit preparation only and keep external execution disabled. Activation must not enable external executors, communications, spending, or owner powers.

## Preparation evidence and authorized execution boundaries
- Private local source: `.commandcore-runtime/staff-profile-preimport.json` remains unchanged, including historical status `PREPARED_NOT_IMPORTED`. The six payloads are now verified active in the registry; private `staff-activation-20260911-*-result.json` evidence records `ACTIVATION_PASS`. Never infer current live state solely from the historical source label, import it merely to resume, or commit private evidence.
- Existing implementation: `src/cfh_disposition/staff_profiles.py` and `supabase/functions/commandcore-team-registry/index.ts`; canonical storage: `commandcore-team-registry/members/`. Use existing identity checks and preservation gates; no alternate roster, migration, blind overwrite, or upsert around create-only provisioning.
- Completed activation checks: source hash unchanged; live compatibility/preservation contract enabled; existing bucket private; no identity conflicts; zero preexisting members; six exact create-only saves; read-back and registry-service list match; repeat provisioning performs no writes; external execution disabled. The existing registry helper was used with one OS-locked worker. Any future profile changes require their own scope and preservation review; do not overwrite these verified profiles.
- The one-time `.commandcore-runtime/activate_six_staff_20260911.py` was removed after successful smoke verification under the user's explicit cleanup instruction. Do not recreate it to resume. Preserve original questionnaires, preparation source and activation evidence; the reusable canonical staff/registry implementation remains unchanged.
- Unknown answers, capacities, numeric limits, manager references, buyer-ID workflow, and system-of-record details remain unresolved as recorded in the private profiles. Do not silently fill them in. Any action dependent on those details stays blocked until verified.
- If the private source is unavailable in another checkout, stop activation and request the existing approved source through a private channel; do not fabricate replacement profiles.
