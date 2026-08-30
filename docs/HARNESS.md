# CommandCore Test & Simulation Harness

The CommandCore Test & Simulation Harness is a small, repeatable safety layer for exercising existing CommandCore behavior against obviously fake Deal data. Its purpose is to prove what the system intended to do and why dangerous actions did not happen.

It is **not** a second application, a Sandbox product, a replacement CRM, or a new commercial Streamlit workspace. It does not add Edge Functions or enable live email, SMS, signing, advertising spend, authenticated scraping, CRM production writes, or money movement.

## Default mode

The harness defaults to `simulation`. Production is never inferred from a missing or invalid value.

- `simulation` records intent only. It makes no provider calls and does not write production CRM data.
- `staging` may route `crm.commit` through an explicitly supplied staging executor only. Send, sign, spend, authenticated scrape, money movement, and production CRM writes remain blocked.
- `production` is fail-closed. A record marked `internal_only` is blocked. `external_action_started` must be explicitly `true`; consequential action types also require an already-approved Owner Approval record.

The harness reuses CommandCore's existing `internal_only` and `external_action_started` fields. It does not create a parallel approval or safety flag system.

## Side-effect action types

All harness-connected consequential actions use `cfh_disposition.harness.side_effects.SideEffectBus`:

- `email.send`
- `sms.send`
- `offer.send`
- `contract.send`
- `contract.sign`
- `ads.spend`
- `ads.authorized_scrape`
- `crm.commit`
- `money.move`

New automation and agent work should use this same bus rather than adding another outbound safety mechanism. This first slice does not claim every historical provider call in the repository has already been migrated to the bus.

## Fixture family

`FIXTURE_DEAL_HARRIS_ST` contains one synthetic Contact, Property, Deal, Offer, Contract draft, Task, inbound Communication, and pending Owner Approval item. IDs are stable and begin with `FIXTURE-`. Every fixture record is `internal_only: true` and carries `fixture_source: commandcore_harness` provenance.

No fixture loader touches Supabase or the network.

## Scenarios

### Offer analysis, no send

```bash
python -m cfh_disposition.harness.runner --scenario offer_no_send --mode simulation
```

This calls the existing CommandCore Offer Engine math, creates an internal-only offer result, records a simulated CRM commit, attempts `offer.send` through the bus, and proves the send is blocked.

### Contract build, no sign/send

```bash
python -m cfh_disposition.harness.runner --scenario contract_no_sign --mode simulation
```

This calls the existing Illinois contract generation/storage pipeline against an in-memory fake private storage client. The fixture already contains contract version 1, so the scenario builds version 2 without overwrite. It then attempts `contract.send` and `contract.sign` through the bus and proves both are blocked.

## Reports

Each CLI run writes:

- `artifacts/harness-report.json`
- `artifacts/harness-report.md`

The report includes intended actions, blocked actions, approval-required actions, provider-call count, scenario artifacts, and the exact block reason for each action.

A successful simulation report should show `provider_calls: 0`.

## Tests

```bash
pytest tests/test_commandcore_harness.py
```

The tests require no network and use only fakes/in-memory data.

## Adding a scenario

1. Reuse an existing CommandCore engine or add a thin adapter around it.
2. Load the canonical fixture family or add only the minimum synthetic fixture data needed.
3. Route every proposed side effect through `SideEffectBus`.
4. Assert the expected bus decision and provider-call count.
5. Return a `HarnessReport` with the relevant internal artifact references.
6. Add network-free pytest coverage.

Do not use the harness as a reason to duplicate an existing product workflow or approval queue.
