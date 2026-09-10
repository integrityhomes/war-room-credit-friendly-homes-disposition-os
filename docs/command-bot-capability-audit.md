# Command Bot capability audit

This milestone extends the existing CorePilot runtime. “Works” means covered by
local runtime/regression scenarios, not that every real record contains the facts
needed to answer. Action tests use fictional canonical transports only.

| Capability | Before | After | Should Command Bot handle it? |
|---|---|---|---|
| Natural-language routing and clarification | Partial: phrase gaps | Expanded with tested phrases | Yes |
| Property/deal/contact lookup | Works | Preserved; archived records excluded | Yes |
| Session context | Partial: created tasks not selected | Created tasks/drafts retain IDs; unique message/deal queues select context | Yes |
| Recorded terms, ownership evidence, related records | Partial: label-only answers | Property facts, field warnings and canonical links shown; no legal ownership inferred | Yes, verified facts only |
| Property-change questions and protected access alerts | Works with phrase gaps | Payment, returned-available and lockbox wording supported | Yes, never disclose codes |
| Stale inventory and portfolio sales diagnosis | Works with follow-up gaps | Pronoun follow-ups and threshold queries; existing field evidence included | Yes, recommendations only |
| Priority review order | Works | More natural priority wording | Yes, recorded evidence only |
| Deals, blockers, timeline, next action | Works with queue gaps | Attention queue selects only a unique deal | Yes |
| Create/assign/reassign/reschedule/complete tasks; notes | Works with context gaps | Immediate follow-up after creation; missing note asks for content | Yes, existing internal-only controls |
| My Work and management canonical task consistency | Works | Preserved | Yes |
| Overdue/due-today work | Partial: summary count, unfiltered listing | Filtered canonical task listing | Yes |
| Team workload | Partial | Canonical open-task counts; no capacity assumptions | Yes; broader management signals remain in existing views |
| Communications and private drafts/revisions | Works with queue gaps | Explicit response status recognized; unique recipient context retained | Yes, private only |
| Approvals | Works for listing | Explain existing projection; ambiguous item asks clarification | Yes, never approve/sign |
| Seller/buyer/property/deal relationships | Works for direct/deal links | Linked offers/documents/transactions/work exposed | Yes; missing links remain missing |
| Marketing evidence and field uncertainty | Works in advisor | Existing owner/client/insurance evidence and warnings surfaced | Yes, no invented performance or facts |
| External sends, publication, legal/financial actions | Disabled | Disabled | Prepare/review only |
| VA profiles, Gordon and new specialist agents | Missing/deferred | Not built | Future milestone |

No property reader, clock persistence, scheduler, schema, or duplicate storage was
introduced. Real-time provider semantics and legal ownership cannot be proven by
the offline simulator. Management capacity, unlinked records and unavailable
evidence remain explicit limitations, not guessed answers.

The permanent simulator includes the real Streamlit property → changes → diagnosis
→ task → reschedule → reassign → note → complete conversation, portfolio questions,
messages → draft, approvals, and deal blockers. Existing safety and import tests
remain part of the full suite. The known guarded cross-process lock limitation is
unchanged; imports remain serialized.
