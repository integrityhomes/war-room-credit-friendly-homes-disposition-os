# Property change detection

Open **Deals / Properties → Property Changes**. Opening the page checks the source
automatically; **Check for changes** refreshes it. CorePilot's property-change
questions and attention summary use the same read-only detector. No tasks,
activities, property updates, deals, communications, or closing dates are written.

The existing regional adapter and canonical comparison determine eligibility.
Ambiguous/duplicate rows remain excluded. Unmatched canonical properties always
produce a missing/needs-review event, even when an invalid source row prevents
proving disappearance. Source-sheet sold status is not a closing assertion.

Events identify semantic differences from canonical facts, not a historical feed
of applied updates. The source fingerprint excludes row order, observation time,
and formatting-only numeric changes. Event IDs use source identity, property
identity, change types, and normalized before/after facts. All outstanding changes
remain visible; identical semantic events are emitted only once per checkpoint.
An identical change that disappears and later recurs keeps the same event ID.

## Prepared worker, not activated

`python scripts/detect_property_changes.py --checkpoint <prior-checkpoint.json>`

This performs one complete read and prints aggregate counts plus the next
hash-only checkpoint to stdout. It does not save the checkpoint. A failed read
returns a failure exit code and does not advance state. Without a prior checkpoint,
every outstanding difference is considered newly detected.

The web app shares a lock-protected in-memory checkpoint across sessions in one
server process. It is lost on restart and is not shared across multiple workers.
No property facts or private URLs are included in the checkpoint. Detailed evidence
is reconstructed from current sheet and canonical records and kept in memory.

The repository already uses GitHub Actions schedules. A future job can invoke this
worker using the existing Python dependencies, restore the checkpoint, and publish
the next checkpoint only after a successful run. No workflow or cron is activated
in this milestone. Confirm available Actions minutes and Google read access before
activation; this milestone installs nothing, runs no hosted job, and spends $0.

Reliable scheduled deduplication needs a durable checkpoint and concurrency control.
The existing Supabase Storage JSON mechanism can hold a small detector checkpoint
without a database/table/schema migration or a second property database. Creating
that checkpoint and any persisted attention events requires separate write approval.
Use conditional writes/ETags or a single worker before enabling multiple scheduled
runners. Scheduled results must be made available to the UI through that approved
checkpoint/event path; today's UI reads fresh data directly.

Until then, owner/VA next actions are read-only recommendations in Property Changes
and CorePilot, not CRM tasks. All canonical facts remain unchanged.
