# Property change detection

Open **Deals / Properties → Property Changes**. The page and CorePilot read the
latest successful local evidence; **Check for changes** forces a fresh source read.
On first use without a checkpoint, the page runs a check. No tasks,
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

## Local scheduled worker

`python scripts/detect_property_changes.py --scheduled`

This quietly performs one complete read and atomically saves its checkpoint and
derived change evidence under `.commandcore-runtime/property-changes/` in this
checkout. That folder is gitignored and must not be committed or published. It is
a disposable local detector cache, not a second property database: unchanged
properties and raw sheet rows are never copied into it. Evidence contains only
outstanding changes, review reasons, identifiers, and before/after values. The
existing canonical properties remain authoritative.

The checkpoint survives restarts and is shared by the runner and the web app.
An OS file lock prevents overlapping processes from checking the same source.
Atomic replacement keeps previous evidence intact if saving is interrupted. A
failed provider read records a sanitized local failure status, keeps the last
successful checkpoint/evidence, and exits with code 1. The page and CorePilot warn
when showing retained evidence after a failed run. The page checks local status
every 60 seconds; this UI timer does not call Google or CRM.

Windows Task Scheduler is the selected zero-service-cost scheduler. Prepare with
`./scripts/register_property_check_task.ps1`; register explicitly with `-Activate`.
It uses the existing `.venv/Scripts/pythonw.exe`, so there is no console window,
new package install, stored password, elevated task, cloud job, or paid service.
The task name is **CommandCore Property Change Checks**. The default cadence is
every two hours, first scheduled five minutes after registration. The task is
limited to the signed-in current user and may run on battery. The computer must
be on, awake, signed in, and online; Streamlit need not be running. It does not
wake the machine. Missed starts are run when available, overlapping runs are
ignored, and a run is stopped after 20 minutes. Inspect Last Run Result and Next
Run Time in Task Scheduler; 0 means success.

No database/schema migration, credential changes, deployment, or external writes
are required. The registration script refuses to replace a conflicting task. If
Windows refuses normal-user registration, stop rather than elevating the task or
changing security settings. To pause, disable this task in Task Scheduler; no CRM
records are affected. Existing credentials are read from this checkout's Streamlit
secrets by the runner; never place credential values in task arguments.

The original `--checkpoint <file>` mode still reads an explicit checkpoint and
prints the proposed next checkpoint without saving it. It cannot be combined with
`--scheduled`. Owner/VA next actions remain read-only recommendations, not CRM
tasks. No calls, texts, emails, imports, deletions, deals, or closing dates occur.
