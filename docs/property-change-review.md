# Property Change Review — preview only

Open **Deals / Properties → Property Changes**. The existing page is now titled
Property Change Review. It shows property, change type, source, first detected
time (or last observed time for older checkpoints), old/new values, and the next
review action. No changes currently means an empty queue, not sample events.

**Review** re-reads the current sheet and canonical records. The event must still
match that fresh comparison before any patch is prepared. Normal numeric facts
and source classification get an exact field patch, expected old values, and a
canonical record fingerprint. Existing canonical field aliases are respected.
Blank, N/A, invalid, ambiguous, stale, archived, and unsupported changes block
the whole patch. Legal text and unrecognized insurance wording require explicit
investigation. Missing source rows never produce patches or status changes.

New properties must pass the existing baseline builder and global duplicate
comparison. A validated creation proposal may be inspected; it is never created.
All source rows excluded for review remain excluded. Sold/unavailable is solely
sheet classification, never a deal, closing date, payment, or legal assertion.

**Ignore this detected change**, **Needs investigation**, and **Return to pending**
save only local review metadata in the same gitignored detector cache. Decisions
apply to an exact event ID. Different source values create a distinct review item.
The scheduled checker preserves decision history and first-detected evidence;
resolved events disappear from the current queue while their local evidence is
retained. Repeated identical decisions and detections do not duplicate items.
This local audit cache is not a permanent/compliance-grade central audit log.

**Apply safe property update** is disabled on screen and the server-side function
always raises PermissionError. There is no live writer in the review module.
Tests simulate applying a patch to an in-memory record and verify the next
comparison removes the pending difference. The two-hour checker is unchanged.

Before enabling live Apply, require a new explicit approval, another fresh source
and canonical check, an atomic conditional write against the expected record
version/fingerprint, and durable approved audit handling. The current CRM upsert
does not provide that concurrency guard and must not be used as blind Apply.
The existing JSON storage can support conditional writes and audit metadata
without a table/database schema migration; implementing and verifying that
write boundary is a separate milestone. No such writer is enabled here.
