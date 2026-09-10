# Stale inventory inside Command Bot

Ask “Which properties are getting stale?”, identify a property, then ask “Why
isn't this property selling?” or “What should we do to sell this one?”. The
existing attention answer includes stale inventory. No separate app was added.

Thresholds are the code tuple STALE_THRESHOLDS: 10 days needs attention, 14 higher
priority, 21 urgent disposition review. ONLY validated yellow-highlighted active
properties qualify. White means **Not ready to market**, with no stale aging.
Sold/unavailable, paused, archived, missing, ambiguous and unknown-color rows
cannot trigger stale alerts. White never means sold, deleted or closed.

The values reader previously received no formatting. Its opt-in marketing read
now uses one additional bounded read-only spreadsheets.get request for effective
background colors on the address cells (column A, the existing property identity
column). Live inspection confirmed yellow address-row markers with green input
cell accents; those other input colors are not marketing status. Pure yellow and
white are recognized; other/unresolved colors remain unknown. The address values
must match between the values and formatting responses, or the complete read
fails safely. Baseline/import callers retain their existing values-only behavior.
No new scopes, credentials, canonical fields or database schema are required.
See [Google's read-only grid data API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get).

An initial yellow period may use an explicit verified marketing_started_at,
listed_at or first_listed_date. Otherwise first verified yellow observation is
**Tracked marketing since**, with wording **CommandCore has tracked this property
as marketed for X days**. Verified dates use **Actively marketed for X days**.
Generic active/import/update dates and old availability-only checkpoints cannot
establish marketing age. Missing evidence means **Marketing age cannot yet be
verified**. Yellow to white or sold stops aging. A later yellow observation starts
a new period; prior listing dates do not prove continuity across that interruption.
All lifecycle observations stay in the existing local evidence checkpoint.

The existing two-hour checker reuses validated matching and stores only derived
observation metadata, hashes and attention evidence in its existing gitignored
checkpoint. No second property database, new scheduler or external notification
exists. Same property/marketing period/escalation level has a stable event ID;
repeated checks retain attention without duplicate events. Pricing/payment
fingerprints and existing archived detector evidence track last observed
meaningful changes. Observed dates do not assert exact effective change dates.

Advice distinguishes recorded facts, possible causes and recommendations. Exact
recorded buyer objections and blocked linked tasks support review hypotheses;
age alone never proves poor pricing, insufficient marketing or bad condition.
Ranking favors explicit evidence, potential sales impact and a low-risk review
before changes. Numbers are never calculated as a recommended price or payment.
Missing buyer/marketing/photo/comparable/condition evidence is explicit. The
advisor does not read other platforms or run external market research.

Optional preparation can preview an explicit user-proposed price/payment target
or marketing review/copy. No target is inferred. Current recorded availability
and existing source changes gate these previews; all require fresh verification
before any future use. Send, save, task creation, approval, property Apply and
publication remain unavailable. No CRM/Sheet data, schema or credentials change.
