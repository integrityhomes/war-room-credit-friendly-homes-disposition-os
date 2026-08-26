# Credit Friendly Homes — Automatic Launch Webhook Contract

The Disposition OS must never count an external channel as launched from a generic HTTP 200 alone.

## Request

The app sends `credit_friendly_homes.campaign.approved` with the property, campaign, tracked buyer links, and all 15 channel packages.

Channels have one of three launch actions:

- `Live in Disposition OS` — internal property landing page.
- `Automatic publishing workflow` — external automation is expected to execute the channel.
- `Manual final platform post` — package is prepared/delivered, but a human must complete the final platform post.

## Required success response

The publishing workflow must return JSON containing a `channel_results` array. Every channel whose `launch_action` is `Automatic publishing workflow` must be represented exactly once with a confirmed status.

Example:

```json
{
  "accepted": true,
  "dispatch_id": "cfh-2026-08-26-001",
  "channel_results": [
    {"channel_key": "email", "status": "sent", "external_id": "msg_123"},
    {"channel_key": "sms", "status": "scheduled", "external_id": "job_456"},
    {"channel_key": "instagram", "status": "published", "external_id": "post_789"}
  ]
}
```

Accepted confirmed statuses are: `accepted`, `queued`, `scheduled`, `sent`, `published`, `posted`, and `live`.

If an automatic channel is missing, duplicated, malformed, or reports a non-confirmed status, the Disposition OS treats the dispatch as failed and does not mark external automatic channels launched.

Manual-final-post channels such as Facebook Marketplace, Facebook Groups, classifieds, and Nextdoor are not allowed to become Posted merely because the webhook accepted their package. They remain Ready until the final platform post is confirmed.
