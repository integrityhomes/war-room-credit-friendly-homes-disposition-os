# Whole-workbook source coverage

The shared baseline reader now discovers all worksheet titles before its batch
read and excludes the explicitly ignored Sheet36. It still fails closed if an expected baseline tab disappears. It reads
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
properties. Within a SOLD row, historical sold classification takes precedence
over its fill color and never proves a closing. A separate verified current
yellow/white inventory row supplies current state for the same physical address.
White and unknown rows cannot age.

Each tab is classified as property/inventory, support/cache/system, or unknown /
needs review. The confirmed non-property restriction list is support data only
when its explicit heading and row structure agree; a changed layout is retained
for review. Parser and color inspection use the same repeated-header test.

Raw fill-color counts are distinct from lifecycle counts: a white SOLD row is
still sold/unavailable, while any color on an unclassified tab remains unknown.
Complete address keys are reconciled separately for known inventory tabs and
unclassified tabs. Unresolved addresses prevent certifying a final unique-property
total; duplicate occurrences and property-candidate review counts remain visible.
Support entries and unresolved non-property text are not counted as properties.

Reconciliation may opt into `verified_format_recovery=True` on
`regional_sheet_properties` and `sheet_address_parts`. This normalizes explicit
state-name/punctuation/ZIP spacing and a single address separator, and removes
unambiguous square-foot or monthly unit suffixes. Missing components, combined
addresses, alternatives, fees, responsibility notes and conflicting room counts
remain unresolved. It does not use seller addresses or infer geography from a tab.
The scheduled reader does not opt in: reconciliation must not start or change
marketing clocks before review. This option performs no persistence or import.
For the explicitly mapped total monthly payment only, an exact numeric amount
followed by PITI is accepted as a formatting label. PIT-only, plus-insurance,
servicing-fee and other qualified amounts remain in review. PITI is never
stripped from a principal-and-interest field.

The legacy requirement for a Sales Price column remains enforced. The canonical
row model permits an absent asking price, but a future change to that policy must
preserve purchase price separately and never infer asking price. The original
empty-CRM baseline scope checks and disabled import entry point are unchanged;
an additional-property import needs its own explicitly approved scope.

Command Bot captions distinguish yellow source candidates from the validated
canonical properties eligible for marketing-age tracking. Property Changes has
a Workbook source coverage expander with per-tab evidence and header row
locations. The existing scheduled runner uses the same reader and checkpoint.
Continuous, valid yellow observations keep their original marketing clocks.

Historical SOLD occurrences are retained as source evidence, not counted as
competing current rows. The existing checkpoint retains their source locations
and explicitly records that no closing is verified. Conflicting identities,
multiple current occurrences and invalid current facts still require review.
An invalid current row never falls back to its historical SOLD state. If the
current row disappears while its known history remains, it becomes missing /
needs review, without inferring a sale or deletion.

A returned yellow property starts a new prospective marketing period rather
than reusing a historical listing date or prior marketing clock. Repeated valid
yellow observations preserve that new period. History alone establishes no
foreclosure, ownership, closing, payment or legal date. Reconciliation reads do
not write live marketing checkpoints or import any properties.

Source coverage does not authorize importing newly discovered properties,
changing business facts, publishing, sending, or exposing access codes. An
unverified newly discovered tab needs explicit source-classification review
before any future import can be considered.

Marketing eligibility is separate from complete import and sales-analysis
validation. `marketing_checkpoint_preview` uses the existing canonical identity
matcher with identity-only projections and verified current yellow evidence.
Financial/detail errors remain on the original source rows for import and
analysis review; they do not suppress verified canonical marketing eligibility.
Unmatched yellow sources remain visible in reconciliation without becoming
canonical properties or acquiring canonical marketing clocks.

This pure preview preserves existing continuous marketing starts and prepares
prospective local checkpoint patches only where a current period is missing.
It retains historical source references without inferring a closing or legal
date. It does not persist, import, or call the scheduled writer. Connecting this
eligibility path to checkpoint persistence awaits explicit approval; preparation
must not cause the existing scheduler to create the proposed clocks.

Every candidate row now carries ephemeral `source_fields`: source column/header,
raw value, safe interpretation and per-field review reason. All columns are
retained, including unlabelled cells, repeated headers and currently unknown
fields. Section labels remain source labels, not inferred ownership. Explicit
owner/seller and LLC/trust columns are read without assuming company ownership.
Tax periods and purchase prices stay distinct from monthly taxes and asking prices.
Buyer-responsible insurance is an interpretation without a guessed dollar amount.
Last Update accepts source text without inventing a date; explicitly dated
columns require a valid date. Qualified fees, payments and room counts remain
reviewable in their original wording. Import gates remain separate and strict.

Other successfully normalized facts survive an invalid field. A whole-row import
warning does not mean all its fields were unreadable. Lockbox codes remain in the
existing restricted field path; field evidence replaces codes and access notes
with protected markers, and ordinary row representations omit field contents.
Field evidence is not another property database and is not automatically copied
into canonical CRM records, alerts, or checkpoint storage.

The existing Final Property Baseline page also offers a missing-property import
reconciliation. Its loader uses the same full-workbook reader with explicit
format recovery, reads canonical properties and existing checkpoint observations,
and creates no records. Results group complete addresses once, prioritize current
yellow rows over historical SOLD evidence, and retain exact blocking reasons.
The existing strict canonical normalizer and identity comparison are reused.
Verified buyer-responsibility interpretations and textual Last Update evidence
are distinguished from invalid numeric/date facts. Other import blockers remain.
Field warnings can coexist with readiness, so warning and blocked counts overlap.
Both the page and the service have no import or checkpoint-write action.

The current-inventory decision is separately scoped to missing yellow/white
properties. Verified identity, legitimate current source/color, and duplicate
safety govern canonical-creation preview eligibility. Optional detail errors
remain field warnings and never become guessed values. The same identity-only
comparison used for marketing eligibility is reused, including current/history
handling and conflicting-ID safeguards. Historical-only records are excluded
from this operational set and remain in the full reconciliation for later review.
Existing marketing starts are preserved; missing starts are proposals only.
