# Command Bot safe action preparation

Use the existing Command Bot session: identify a property or deal, then ask for
a draft, proposed task, next action, approval review, or property update preview.
The additional Prepared action section shows the subject, proposal, reason and
expandable source facts. Every preview says **NOT SENT / NOT SAVED**. There is no
execution button, provider writer, task creation, approval or Apply path.

Examples: “Have Sabrina follow up tomorrow”, “Prepare a task for Gabe to check
this deal”, “Prepare the next step”, “Draft a reply”, and “What should I say back?”
Task assignees and timing come from the request, not hard-coded routing. Relative
timing is retained as proposed wording, not converted into a saved due date.

Viewing one recorded message (including a uniquely selected last conversation)
retains its ID in session context. Drafts require a unique recorded message and
use the existing Nevaeh context and sensitivity checks. Missing consent, STOP,
suppression, ambiguous routing and sensitive communications withhold the draft.
A STOP elsewhere in the recipient's recorded communications also requires
investigation. This conservative preview does not resolve or grant consent.
Even a safe neutral draft requires channel authorization before any future send.

If only a property is known and no recipient/message is recorded, Command Bot
asks for the missing context. It does not invent a seller, conversation or facts.
Unclear action requests similarly ask for clarification.

Property updates reuse the existing safe patch builder and current canonical
records with the detector's dated evidence. Preview is not fresh-source approval;
any future Apply must revalidate the source. No detector infrastructure changed.
Deal next steps and approval preparation reuse existing task/approval projections.
All previews remain ephemeral; no new storage or schema is needed.
