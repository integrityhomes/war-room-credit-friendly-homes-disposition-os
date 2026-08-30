# CommandCore Commercial Completion Standard

CommandCore is one commercial operating system organized around the six approved user-facing areas:

1. Home / Command Center
2. Leads & CRM
3. Deals
4. Tasks & Follow-Up
5. Marketing & Dispo
6. Management

The Unified Deal Record remains the operational center of the product.

## Completion rule

A feature is not complete merely because its backend logic works. A launch-ready feature must also be understandable and usable by a normal team member without knowledge of Streamlit, Supabase, edge functions, internal queues, payloads, or repository structure.

Every primary workflow should provide:

- one obvious next action;
- plain-language status and blockers;
- useful empty states rather than blank tables;
- consistent names for the same business concepts;
- Deal context preserved when moving between related work;
- confirmation after meaningful actions;
- safe failure messages that say what happened and what did not happen;
- no public exposure of private document/storage details;
- no duplicate entry when CommandCore already knows the fact;
- automatic routine work where reliable, with approval gates for consequential financial/legal actions.

## Navigation rule

Working specialty engines may remain in the repository, but normal users should not have to navigate dozens of internal tools. Mature specialty capabilities should be surfaced through the six approved areas or kept as advanced/admin functions.

Developer/test/setup screens are not part of the normal commercial product navigation.

## Deal workflow target

A user should be able to move through the ordinary lifecycle without leaving the CommandCore experience:

lead intake → qualification/follow-up → Deal → analysis/offer → approval → contract/document work → execution evidence → title/closing → marketing/disposition when applicable → completion/history.

The system should retain complete Deal history and provenance throughout that lifecycle.

## Safety boundary

Commercial polish does not weaken approval controls. CommandCore may automate routine internal work, but binding agreements, legal-term changes, signing, money movement, bank-information changes, and similar consequential actions remain approval-controlled.
