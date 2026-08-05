# Dwelyx Results Tracking & Attribution Connection

## Purpose

Dwelyx remains the buyer system of record. The Credit Friendly Homes Disposition OS receives only pseudonymous outcome events so it can attribute registrations, applications, showings, contracts, and filled homes to the marketing source, campaign, and property that produced them.

The receiver must never receive buyer names, email addresses, phone numbers, applications, documents, income, credit information, or other buyer personal information.

## Event flow

1. A buyer clicks a tracked Credit Friendly Homes link and reaches Dwelyx with `source`, `medium`, `campaign`, and optional `property_id` values.
2. Dwelyx preserves those attribution values on its internal buyer or session record.
3. When a supported result occurs, Dwelyx creates one immutable event with a unique `event_id`.
4. Dwelyx signs the exact JSON body with the shared `DWELYX_WEBHOOK_SECRET`.
5. Dwelyx sends the event to the Supabase Edge Function.
6. The receiver verifies the signature, timestamp, event ID, allowed fields, property requirements, and Dwelyx deep-link host.
7. The receiver writes one private object per event using `upsert: false`.
8. A retry with the same `event_id` returns success as a duplicate and does not create a second result.

## Supported events

| Event type | Result stage | Property ID required |
|---|---|---|
| `buyer.registered` | Registered | No |
| `buyer.qualified` | Qualified | No |
| `application.started` | Application Started | Yes |
| `application.submitted` | Application Submitted | Yes |
| `showing.requested` | Showing Requested | Yes |
| `showing.scheduled` | Showing Scheduled | Yes |
| `contract.pending` | Contract Pending | Yes |
| `contract.signed` | Contract Signed | Yes |
| `home.filled` | Filled | Yes |

## Required event body

```json
{
  "schema_version": "1.0",
  "event_id": "evt_12345678",
  "event_type": "application.submitted",
  "occurred_at": "2026-08-05T20:00:00Z",
  "dwelyx_buyer_id": "buyer_abc123",
  "dwelyx_property_id": "dwelyx_property_456",
  "cfh_property_id": "credit_friendly_homes_property_uuid",
  "source": "credit_friendly_homes",
  "medium": "nextdoor",
  "campaign": "saltville_august_2026",
  "dwelyx_record_url": "https://app.dwelyx.com/admin/buyers/buyer_abc123",
  "test_mode": false
}
```

`dwelyx_record_url` is optional and must use HTTPS on `dwelyx.com` or one of its subdomains.

## Required headers

```text
Content-Type: application/json
X-Dwelyx-Event-Id: evt_12345678
X-Dwelyx-Timestamp: 1785960000
X-Dwelyx-Signature: sha256=<hex HMAC digest>
```

The signature input is:

```text
<Unix timestamp>.<exact request body bytes>
```

Use HMAC SHA-256 with `DWELYX_WEBHOOK_SECRET`. The receiver rejects requests outside the five-minute replay window.

## Deploy the receiver

The receiver source is located at:

```text
supabase/functions/dwelyx-results/index.ts
```

From a workstation authenticated to the same Supabase project used by the Disposition OS:

```bash
supabase functions deploy dwelyx-results --no-verify-jwt
supabase secrets set DWELYX_WEBHOOK_SECRET="replace-with-a-long-random-shared-secret"
```

Supabase provides `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to the Edge Function. Do not place the service-role key in Dwelyx or in browser code.

Add the same shared secret to the Disposition OS Streamlit secrets:

```toml
DWELYX_WEBHOOK_SECRET = "replace-with-the-same-long-random-shared-secret"
DWELYX_RESULTS_ENDPOINT = "https://your-project.supabase.co/functions/v1/dwelyx-results"
```

The endpoint override is optional because the app can derive the normal function URL from `SUPABASE_URL`.

## Add the sender to Dwelyx

Use the example at:

```text
docs/examples/dwelyx_results_sender.ts
```

The sender must run on the Dwelyx server, background worker, or protected serverless function. It must not run in a buyer's browser because the shared secret cannot be exposed to users.

## Delivery rules

- Generate the `event_id` once when the business event occurs.
- Save that event ID in Dwelyx before the first delivery attempt.
- Retry network failures with the same body and same event ID.
- Generate a new timestamp and signature for each retry.
- Treat HTTP `200` with `duplicate: true` as success.
- Treat HTTP `202` as newly accepted.
- Do not send personal information or arbitrary metadata.
- Preserve the original tracked `medium` and `campaign` values throughout the buyer journey.
- Use the Credit Friendly Homes property UUID in `cfh_property_id` when it is known.

## Connection validation

1. Open **Dwelyx Results Tracking & Attribution Center**.
2. Use **Signed Test Event** to confirm the Python contract, private bucket, and dashboard.
3. Deploy the Edge Function.
4. Send one test-mode event from the Dwelyx server.
5. Confirm it appears only when **Include test events** is selected.
6. Send one real registration event.
7. Confirm the live-event timestamp and marketing channel appear in the dashboard.
