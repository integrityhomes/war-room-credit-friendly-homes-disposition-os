# Internal work management

Command Bot now selects a unique task from “What work does Jordan have?” and
retains its canonical task ID for “Move that to Friday”, “Give it to Morgan”,
“Add a note that we are waiting on the seller”, and “Mark it done”. Multiple
matches clear the task selection and request an exact title or ID using
“Select task …”. A new property selection clears unrelated work context.

Only records explicitly marked internal_only can be updated. Reassignment names
must match an existing assigned_to or assigned_worker value in current canonical
records. No person is invented or hard-coded; an unknown name requires clarification.
Dates follow the same local-calendar rules as internal task creation.

“Show the private draft” retrieves a uniquely matched unsent draft in context.
“Revise that draft with …” stores the user's exact replacement copy privately.
This is user-provided copy requiring verification, not an assertion of verified
property or legal facts. Consent warnings and existing source evidence remain
on the record. No send, publication, approval or legal execution is available.

Changes use the existing canonical CRM get/upsert interface, limited to task
status, due_date, assigned_to, internal_notes, and private draft body. The same
record carries internal_history entries with actor, time, old values and new
values. No second task, draft or audit store and no schema migration is needed.
Unchanged updates and repeated identical notes produce no additional history.

The writer rereads the full expected record immediately before updating and
rejects a stale snapshot. Local threads serialize updates. The existing CRM
endpoint does not offer an atomic compare-and-swap across independent clients;
simultaneous edits from another app remain a limitation. Post-save verification
and uncertain-result wording prevent false success claims. No external changes
or deletions are performed.

The full task lifecycle and draft revision run through the actual Streamlit form
with isolated fictional canonical transport. Automated tests never complete or
alter the real production follow-up task.
