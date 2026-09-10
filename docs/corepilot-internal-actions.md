# Command Bot internal actions

Explicit commands can now create canonical internal tasks, save private communication
drafts, and record proposed next actions as canonical activities. Read questions and
general suggestions remain read-only or previews. Prices, terms, property facts,
deal stages, approvals, sending, and publication remain disabled.

Examples with a selected property or deal:

- Have Jordan follow up tomorrow.
- Give Morgan a task to check this property Friday.
- Make me a task to review this tomorrow.
- Draft a reply.
- Save that reply as a draft.
- Prepare the next action for this deal.

"Me" requires the existing session worker name; without it the bot asks for a name.
Assignees are requested names, not inferred contacts. Dates use the local app
calendar; weekday names mean the next occurrence, including today. A missing or
invalid due date requires clarification. No contact or earlier event is invented.

The existing Nevaeh consent, STOP, and legal/financial checks still gate drafts.
Only a verified inbound message with a linked recipient can produce a saved reply.
Saved drafts retain the original communication ID, links, source evidence, warnings,
channel, draft status, and outbound_draft direction. They are excluded from the
inbound attention queue. They have no send/dispatch path.

The runtime uses the existing private commandcore-crm-core bucket and canonical
JSON record format, following the baseline loader's create-only upload pattern.
It never upserts, provisions buckets, migrates schema, or changes credentials.
IDs derive from action content, context, assignee/due date or source message.
Repeated reads and concurrent retries reuse those IDs; storage rejects overwrites.
An uncertain response is verified by reading that same object before reporting
success. An unverified result is reported as uncertain, never as a definite failure
or successful creation. Retry the same command without changing its details.

Canonical source, timestamps, requested-by, request, source facts, and safety
warnings preserve action provenance in the existing records. Recommendations use
the existing activities collection and do not claim completed work. No new task,
draft, property, or audit database is created.

Tests exercise the actual Streamlit form, context, canonical list transport and
create-only writer using fictional in-memory storage. Production business records
are not populated with test tasks or messages.
