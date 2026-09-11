# Canonical marketing attribution — local phase 1

## Existing identity gap

Marketing Home uses `cfh_properties` and `cfh_buyers`. The existing Link Center and
analytics capture channel/medium, campaign and legacy property IDs in `ClickEvent`.
Dwelyx signed events carry provider buyer/property IDs and optional CFH property IDs.
Neither contract establishes a canonical contact or deal identity. Provider journey
labels such as `home.filled` are not verified buyer-closing evidence. Canonical
contacts/properties/deals, communications and tasks already exist under
`commandcore-crm-core`; they must remain the system of record.

## Minimum bridge

`marketing_attribution.py` prepares `marketing_touch` and
`marketing_identity_link` records in the **existing canonical activities collection**.
It reuses `corepilot_internal.create_internal_record`, including create-only upload,
readback and retry checks. There is no new database, bucket, table, CRM object,
provider schema, migration, channel executor or live ingestion hook.

- A touch requires an upstream namespace, stable receipt ID and timezone-aware event
  time. Its deterministic canonical activity ID prevents a repeated receipt from
  creating another event. A changed payload under the same ID fails rather than
  overwriting evidence. Different receipts remain separate touches.
- `tracked_click` consumes the existing `ClickEvent` and persisted object/receipt ID;
  `dwelyx_event` consumes the existing validated Dwelyx event. Their complete original
  payloads are preserved. Source, channel, campaign, post and list evidence remain
  separate. Missing values are UNKNOWN. Dwelyx is a provider, not an invented channel.
- Identity resolves only through unique canonical IDs, exact source/external_id
  pairs, and consistent existing canonical links. Legacy buyer IDs can resolve via
  source `cfh_buyers`; legacy property IDs via `cfh_properties`; Dwelyx buyer IDs via
  source `dwelyx`. These are qualified references, not claims that live crosswalks
  already exist. No address/name/email matching or CRM record creation occurs.
- When a crosswalk is absent, a later explicit, verified canonical binding can be
  appended with its own stable receipt. It preserves the original legacy evidence.
  Resolvable original IDs must agree; competing bindings remain unresolved. The
  caller is responsible for verifying a legacy-to-canonical binding before saving it.
  No automatic event payload can authorize a binding.
- Existing task and communication links can supply identity. A deal is inferred only
  when exactly one existing deal links the known canonical property and contact.
  A property alone never supplies a buyer or deal. Archived, missing, ambiguous or
  inconsistent identity fails closed.
- Each touch retains its original marketing-period token. A token requires a canonical
  available property and timestamped available/yellow observation covering that touch.
  Historical SOLD/pending/paused observations cannot make a touch current. A returned
  yellow observation with a new start produces a different period without changing
  earlier touches or source history. Insufficient timestamp precision and a still-SOLD
  canonical property remain UNKNOWN pending verified canonical evidence.
- Buyer-closing attribution reuses `verified_closing`, requires a valid closing time
  at or after the touch and a unique consistently linked canonical transaction,
  contact, property and deal. Acquisition closings are excluded. Form labels,
  provider filled/sold events and deal status alone never prove a conversion.
  Multiple qualifying closing transactions remain UNKNOWN for review.
- Read-only CorePilot commands `Show marketing attribution` and
  `Show marketing identity continuity` project existing activities and count distinct
  closing IDs. They write nothing and call no provider. Each touch remains visible;
  the view does not invent fractional or first/last-touch credit.

## Scope and remaining validation

Only fictional synthetic data exercises the explicit `save` boundary in this phase.
No production attribution backfill, mapping, closing evidence or remote account has
been certified. Duplicate protection is per stable upstream receipt; future adapters
must retain receipt IDs on retries. Different real inquiries are not collapsed by
fuzzy buyer identity. No business record is created by this bridge.

Owner authority and staff routing are unchanged. Gordon remains a bounded technical
worker; it does not own attribution, business records, approval or marketing actions.
Read-only channel validation is the next milestone, with live writes and activation
still on HOLD. Results and isolated simulator evidence are recorded in SESSION_STATE.md.
