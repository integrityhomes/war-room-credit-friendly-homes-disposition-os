# Command Bot natural-language conversations

Use the existing Ask CorePilot / Command Bot page. Its canonical list reader and
existing inbox, approval, timeline, next-action and property-change projections
remain the sources of truth. No second bot, record store or scheduler was added.

Identify a recorded address, deal name or contact, then ask “What happened last?”,
“What is holding it up?”, “Show me the messages” or “What changed on it?”. Context
contains only canonical identifiers in the current Streamlit session. A new
identified entity replaces it; logout clears it. Unknown addresses and ambiguous
matches require clarification rather than silently using a previous deal.

Named work questions such as “What work does Sabrina have?” and “What does Gabe
need to handle?” use existing task assignments. Approvals use the canonical
offer/document projection. Stuck deals require recorded blockers. Seller/title
message filters require recorded contact links and roles; “last” requires a
recorded timestamp. Missing links, dates or closing facts are never inferred.

The default view remains What I found / Needs attention / Recommended next step.
Source identifiers and timeline evidence sit inside the existing collapsed
details. Recommendations and private drafts are proposals, not completed work.
All write, send and Apply actions remain unavailable. Incomplete or potentially
truncated canonical reads fail closed instead of presenting a false all-clear.

Property-change questions consume the existing detector evidence. Property-only
context works without creating a deal. No property sync behavior was changed.
No schema, credential or security change is needed for these read-only routes.

Regression tests drive the actual Streamlit form repeatedly while substituting
only external provider transport with fictional records. They verify session
context, canonical decoding, rendered answers and list-only provider calls.
