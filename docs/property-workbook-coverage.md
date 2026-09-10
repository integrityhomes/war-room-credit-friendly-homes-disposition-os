# Whole-workbook source coverage

The shared baseline reader now discovers all worksheet titles before its batch
read. It still fails closed if an expected baseline tab disappears. It reads
all returned rows, including hidden tabs, then reads address-cell formatting
for all non-cache tabs. Repeated explicit headers establish each section's
column map; address-column changes are followed in the formatting read too.
The identity cache supplies identity only and never adds inventory records.

Previously unlisted tabs are inspected, but their availability remains
unverified and their candidates stay in review. Existing numeric, full-address,
duplicate and baseline validation remain mandatory. Missing or ambiguous
components are not filled from a regional title. Merged-cell blanks are never
forward-filled into property facts.

Source coverage and import eligibility are separate. The existing local change
checkpoint stores aggregate tab/header/candidate/color counts. Ephemeral address
keys used for aggregate reconciliation are not serialized. There is no new
property database, schema change or import action. Source candidates may be
duplicates, incomplete or otherwise invalid; they are not verified unique
properties. Sold-tab classification takes precedence over marketing color and
never proves a closing. White and unknown rows cannot age.

Command Bot captions distinguish yellow source candidates from the validated
canonical properties eligible for marketing-age tracking. Property Changes has
a Workbook source coverage expander with per-tab evidence and header row
locations. The existing scheduled runner uses the same reader and checkpoint.
Continuous, valid yellow observations keep their original marketing clocks.

Source coverage does not authorize importing newly discovered properties,
changing business facts, publishing, sending, or exposing access codes. An
unverified newly discovered tab needs explicit source-classification review
before any future import can be considered.
