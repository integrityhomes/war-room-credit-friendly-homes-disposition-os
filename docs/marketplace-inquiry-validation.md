# Marketplace source and inquiry validation

Read-only audit, 2026-09-11. No Facebook login, listing action, message, production write, credential change or channel connection was performed. Dwelyx identities and historical evidence were untouched.

## Existing architecture and evidence

| Surface | Verified finding | Remaining gap |
| --- | --- | --- |
| Marketing Home / Marketplace Guard | Assisted package review and manual listing ledger. `MarketplaceListingRecord.listing_id` defaults to an internal UUID; optional Facebook ID can be entered in notes. | Internal UUID is not Facebook provenance. No dedicated structured platform listing URL or inquiry receipt in that ledger. |
| Channel receiver | Marketplace explicitly requires assisted final posting. | Dispatch preparation is not Messenger ingestion. |
| Link Center | Existing tracked links carry medium, campaign and optional legacy property ID. | A generated link is not proof of a Facebook listing, inquiry or canonical property crosswalk. Existing guard excludes external links from Marketplace copy. |
| Marketing Analytics | Counts classified clicks by channel; preserves unclassified/test distinctions. | Clicks are not inquiries or verified buyer conversions. Prior audit's one Marketplace click was UNCLASSIFIED, not proven live. |
| Canonical attribution | Existing `touch`, `bind`, `save`, `project` support append-only receipts and later exact identity resolution. Raw `FACEBOOK_MARKETPLACE` source survives; normalized channel is `marketplace`. | `save` is explicitly not wired to live ingestion or UI commands. Manual capture workflow below is a design, not an activated form or connector. |
| Current canonical evidence | Fresh complete reads: 186 properties, 13 identity activities, zero contacts, deals, communications or transactions, one task; zero Marketplace mentions/touches. | No real inquiry-to-property/contact/deal chain to prove yet. |
| Legacy buyer/property stores | Existing tables read successfully; two buyer rows and one property row, no Marketplace mentions. | No verified Marketplace identity receipt there. No data copied or created. |
| Marketplace ledger | Bucket exists; exact ledger-object GET returned HTTP 400. | Ledger contents UNVERIFIED, not assumed empty. Existing loader catches download errors and returns an empty ledger; audit deliberately did not use that fallback or bucket-creating loader. |
| Authentication/configuration | Existing local Meta token/account settings absent; social publish configuration absent. | Browser login/profile identity unknown. Other webhook configuration does not prove Marketplace access. No secrets printed. |
| Staff | Fresh existing registry routing selects Russ for property marketing, Mars for buyer follow-up, Chase for CFD contracts. Nevaeh inbox reads canonical communications. | No actual Marketplace inquiry exists to prove delivered assignment or handoff. Preserve Mars/Nevaeh partnership; Chase only when verified buyer/deal progression warrants it. Carlos is backup; owner authority stays unchanged. |
| Gordon | Existing bounded local source inspection with no CRM transport or external executor. | Can inspect integration code; cannot claim live Facebook health, read private Messenger, post, message or modify configuration through the existing local handshake. |

Private current read reports: `.commandcore-runtime/marketplace-readonly-current.json` and `marketplace-readonly-routing.json`. The canonical scan used 208 allowed read calls; zero blocked requests, credentials unchanged. No current-production test fixtures were written.

## Supported API boundary

No supported personal-profile Marketplace listing/inbox connector exists in this repository or was established by this audit. Do not invent one or substitute a scraping service. Meta's [official Messenger API collection](https://www.postman.com/meta/messenger-platform-api/collection/iyp204x/messenger-platform-api) requires a Facebook Page and an app with `pages_messaging`; that Page API does not establish access to the personal Marketplace inbox. Direct developer documentation returned HTTP 429 during verification. API status is PARTIAL at the broader Meta platform level; the required personal Marketplace path remains unverified and manual. No new app, credential or authorization scope is proposed.

## Safest manual attribution workflow (not activated)

1. Russ reviews an existing listing and its inquiry in the actual seller profile. Preserve the platform listing ID/URL when visible, inquiry/thread/message identifier, original timestamp with timezone, source `FACEBOOK_MARKETPLACE`, and campaign when known. Unknown values stay UNKNOWN. Never use the ledger's generated UUID as a Facebook listing ID.
2. Match the listing to exactly one existing canonical property using verified identity evidence. Preserve a reviewed crosswalk separately from the inquiry. Sold/unavailable inquiries may be retained historically without making inventory current; returned inventory uses the existing observed period.
3. Prepare an existing canonical attribution receipt through `touch`; namespace must identify the actual source/account, and its stable receipt ID must survive retries. If no provider message ID exists, a reviewed persistent manual receipt reference is required before ingestion. Re-entering the same inquiry under a fresh random ID is not deduplicated automatically. Do not claim a name-only match is verified buyer identity.
4. Link an existing uniquely verified contact, communication or deal only when evidence exists. Otherwise retain an anonymous/property-only receipt and later append `bind`; never overwrite earlier touches or create a second contact. Preserve a separate inquiry per property and each later channel touch.
5. Route marketing ownership to Russ, appropriate owner-finance follow-up to Mars/Nevaeh, and verified forward-moving CFD/closing coordination to Chase. Gordon handles bounded technical diagnosis only. No messages or handoffs were executed by this audit.
6. Resolve closing attribution only from existing verified canonical buyer-deal closing evidence. Marketplace sold/closed wording cannot establish a closing. Any eventual receipt save or workflow implementation requires its own authorized scope; this validation wrote no business data.

## Authentication stop and next evidence

Live Facebook verification is stopped. Shawn must sign into the existing Facebook seller profile actually used for CFH Marketplace listings, with its corresponding Marketplace Messenger inbox. The exact profile name is not recorded in the inspected configuration, so the audit cannot truthfully name it or substitute the CFH business Page. Shawn should identify/open that existing profile and one existing property listing/inquiry for read-only inspection. Do not paste passwords, tokens or secrets into Codex. No other channel access is needed.

## Tests

Eight new synthetic cases cover all nine requested situations, including two-property repeat buyers, later channels, stable-receipt duplicates, missing post ID, later existing-deal binding, unavailable and returned inventory, and verified closing protection. Existing staff/Gordon tests check routing and no-action boundaries. First targeted run: 138 PASS / 0 FAIL. Fixture import lint issues were corrected; Ruff now passes. Final targeted and full simulator results are recorded in SESSION_STATE.md. These controls do not establish live capture or live contact attribution.
