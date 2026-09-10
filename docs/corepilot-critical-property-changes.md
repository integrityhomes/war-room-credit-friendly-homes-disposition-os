# Portfolio property-change attention

The existing two-hour detector now retains source-to-source observations alongside
its canonical comparison. Command Bot combines these changes with stale inventory
and normal attention. No individual address is needed. The existing Property Change
Review page also shows the protected source events; Apply remains disabled.

Watched fields: asking/sale price, monthly payment, down payment, interest rate,
principal/interest payment, insurance, taxes, insurance inclusion, availability,
yellow/white marketing status, bedrooms, bathrooms, square feet, photo link, legal
description, parcel reference and notes. Explicit regional Lockbox / Lock box code
headers now map to the existing source adapter. Missing or invalid inventory rows
remain excluded; an absent code column cannot prove a lockbox change.

Lockbox comparisons use HMAC-SHA256 keyed with the already-configured service key.
The key is never saved in evidence. Only its code fingerprint is checkpointed.
Events contain protected placeholders and say only “Lockbox code changed.” Raw old
codes are not archived. Known codes and labelled access notes are redacted from
general change evidence; lockbox fields are protected in new-property previews.
No code lookup, outbound alert transport, or new permission path is added. Explicit
authorized property detail access remains separate from general attention.

Each actual source transition advances a per-property event revision, including
reversions to an earlier value. An unchanged two-hour check reuses the same event.
Events retain first detection time and source tab. Initial unknown marketing/color
or code observations establish a baseline, not a guessed historical change. Existing
marketing checkpoints seed known yellow/white status on upgrade.

High priority: sold/unavailable, lockbox changes, and a relative change of at least
50% in a known nonzero price, payment, down payment or rate. The latter is a review
heuristic, not proof that a change is erroneous or unexpected. Other supported
changes are normal priority. Source SOLD/unavailable never establishes closing,
fund receipt or deal stage. Existing marketing-aging rules continue unchanged.

Ask “What changed today?”, “Did any prices change?”, “Did any monthly payments
change?”, “Did any down payments change?”, “Did any lockbox codes change?”,
“What properties sold?”, “What came back active?”, “What changed with our marketed
properties?” or “Show me all important property changes.” Today uses the detector's
UTC date. Ordinary amounts are formatted for review; no property values are applied.

All state remains in the existing local change checkpoint and evidence archive.
There is no schema migration, second property database, external communication,
Google Sheet write, deployment or automatic business update.
