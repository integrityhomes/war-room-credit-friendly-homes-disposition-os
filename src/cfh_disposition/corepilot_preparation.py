"""Pure private action proposals. This module has no writer or execution path."""

import re
from dataclasses import dataclass

from .commandcore_approval_status import build_deal_approval_status
from .commandcore_deal_timeline import build_deal_next_action
from .commandcore_nevaeh_inbox import _message
from .commandcore_secretary_context import ConsentReadState, evaluate_commandcore_communication
from .commandcore_secretary_orchestrator import SecretaryIntent, _classify
from .corepilot_orchestrator import CorePilotResult, _label, _links, _related, _text
from .corepilot_tools import CorePilotActionClass
from .property_change_review import prepare_patch, proposed_value
from .property_sync_preview import FIELD_ALIASES, comparable, first


@dataclass(frozen=True)
class PreparedAction:
    what: str
    subject: str
    proposal: str
    why: str
    source_facts: tuple[str, ...]
    assignee: str = "Not proposed"
    due_timing: str = "Not specified"
    status: str = "NOT SENT / NOT SAVED"


def preparation_intent(query):
    lower = query.casefold().strip()
    requested = bool(re.match(r"(?:prepare|draft|write|suggest|have|propose)\b", lower)) or any(t in lower for t in ("what should i say back", "give me the next action"))
    if not requested:
        return ""
    if "task" in lower or lower.startswith("have "):
        return "Proposed task"
    if "approval" in lower or "offer" in lower:
        return "Owner-approval preparation"
    if any(t in lower for t in ("price change", "down-payment change", "down payment change", "monthly-payment change", "monthly payment change", "terms change")):
        return "Price/terms proposal"
    if any(t in lower for t in ("marketing refresh", "listing", "ad copy")):
        return "Marketing preparation"
    if "property" in lower and "update" in lower:
        return "Proposed property update"
    if any(t in lower for t in ("next step", "next action")):
        return "Proposed next action"
    if any(t in lower for t in ("reply", "response", "text", "say back", "follow-up", "follow up")):
        return "Communication draft"
    return "Clarify preparation"


def prepare_action(query, records, ctx, property_changes=None):
    kind = preparation_intent(query)
    lower = query.casefold()
    entities = {
        key: next((r for r in records.get(entity, ()) if r.get("id") == ctx.get(key)), {})
        for key, entity in (("property_id", "properties"), ("deal_id", "deals"), ("contact_id", "contacts"), ("communication_id", "communications"))
    }
    subject = " · ".join(_label(r, "Recorded communication") for r in entities.values() if r)
    facts = tuple(f"{key}: {r.get('id')} · {_label(r, 'Recorded communication')}" for key, r in entities.items() if r)

    def clarify(question):
        return CorePilotResult("needs_context", (), (), "Provide the missing detail; nothing was sent or saved.", clarification=question)

    def preview(proposal, why, warnings=(), assignee="Not proposed", due="Not specified"):
        action = PreparedAction(kind, subject, proposal, why, facts, assignee, due)
        return CorePilotResult(
            "prepared",
            ("A private action preview is ready.",),
            ("Nothing was saved, sent, created, approved, or applied.", *warnings),
            "Review the preview. Execution remains disabled.",
            action_class=CorePilotActionClass.PREPARE,
            prepared_action=action,
        )

    if not subject:
        if ctx:
            return clarify("The selected record could not be found in the current read. Retry the read before preparing an action.")
        return clarify("Which property, deal, contact, or communication should this relate to?")
    deal = entities["deal_id"]
    if kind in {"Price/terms proposal", "Marketing preparation"}:
        prop = entities["property_id"]
        if not prop or comparable("availability", first(prop, FIELD_ALIASES["availability"])) != "available":
            return clarify("A verified active property is required. No sales or marketing proposal is prepared for unavailable inventory.")
        source_statuses = [
            item.proposed for c in (property_changes.changes if property_changes else ()) if c.evidence.property_id == prop.get("id") for item in c.evidence.changes if item.field == "availability"
        ]
        if any(comparable("availability", s) != "available" for s in source_statuses):
            return clarify("The source reports this property is no longer active. Review its availability first.")
        if kind == "Price/terms proposal":
            field = "down_payment" if "down" in lower else "monthly_payment" if "monthly" in lower else "asking_or_sale_price" if "price" in lower else ""
            target = re.search(r"\bto\s+\$?([\d,]+(?:\.\d+)?)\s*[.!]?\s*$", query, re.I)
            if not field or not target:
                return clarify("Which price or payment field and exact proposed value should I preview? Aging alone cannot establish a safe target or new legal terms.")
            value = proposed_value(field, target[1])
            old = first(prop, FIELD_ALIASES[field])
            return preview(
                f"{field}: {old if old not in (None, '') else 'Not recorded'} → {value}",
                "New value is your unverified proposal, not a source fact or recommendation derived from aging. Owner review and fresh validation are required.",
            )
        if "refresh" in lower:
            return preview(
                "Verify current availability, price/payment facts, photos and buyer feedback; review existing listing channels and prepare refreshed copy.",
                "Proposed review checklist only; missing exposure data does not prove insufficient marketing.",
            )
        required = ("asking_or_sale_price", "down_payment", "monthly_payment")
        if any(first(prop, FIELD_ALIASES[field]) in (None, "") for field in required):
            return clarify("Verify asking price, down payment and monthly payment before preparing listing copy.")
        return preview(
            f"Property at {prop.get('address') or prop.get('property_address')}. Recorded asking price: {first(prop, FIELD_ALIASES['asking_or_sale_price'])}. "
            f"Recorded down payment: {prop.get('down_payment')}. Recorded monthly payment: {first(prop, FIELD_ALIASES['monthly_payment'])}. "
            "Eligibility and terms require review; approval is not guaranteed. Confirm current availability and terms before use.",
            "Private copy uses recorded facts only. Condition, market comparisons and financing promises were not inferred.",
        )
    if kind == "Proposed task":
        match = re.search(r"(?:task for|have)\s+(.+?)\s+(?:to\s+)?(call|check|follow up|review|contact)\b(.*)", query, re.I)
        if not match:
            return clarify("Who should the proposed task be for, and what should they do?")
        assignee, verb, remainder = match.groups()
        due_match = re.search(r"\b(tomorrow|today|next week|on \d{4}-\d{2}-\d{2})\b", remainder, re.I)
        due = due_match[0] if due_match else "Not specified"
        task = verb + re.sub(r"\b(tomorrow|today|next week|on \d{4}-\d{2}-\d{2})\b", "", remainder, flags=re.I)
        return preview(
            task.strip(" ."),
            "Assignee and timing were requested by you; no assignment or due date has been recorded.",
            ("Check consent before any proposed contact; this does not authorize outreach.",) if verb.casefold() in {"call", "contact", "follow up"} else (),
            assignee.strip(),
            due,
        )
    if kind == "Communication draft":
        message = entities["communication_id"]
        scope = next((k for k in ("deal_id", "property_id", "contact_id") if ctx.get(k)), "")
        candidates = [m for m in records.get("communications", ()) if scope and _text(_links(m).get(scope) or m.get(scope)) == ctx[scope]]
        if message and scope and message not in candidates:
            return clarify("The selected message does not belong to the current property or deal. Select its conversation again.")
        role = "title" if "title company" in lower else "seller" if "seller" in lower else ""
        if role:
            people = {c.get("id") for c in records.get("contacts", ()) if role in " ".join(_text(c.get(k)) for k in ("relationship", "role", "contact_type", "lead_type", "company")).casefold()}
            candidates = [m for m in candidates if (_links(m).get("contact_id") or m.get("contact_id")) in people]
            if message not in candidates:
                message = {}
        if not message:
            if len(candidates) != 1:
                return clarify(f"Still working with {subject}. Which recorded message and recipient should I use for the reply?")
            message = candidates[0]
        try:
            safety = evaluate_commandcore_communication(message, contacts=records.get("contacts", ()), properties=records.get("properties", ()), deals=records.get("deals", ()))
        except (ValueError, TypeError):
            return clarify("The communication safety context is incomplete. Review the original message first.")
        subject = f"{safety.person_label} · {safety.property_label} · {safety.deal_label}"
        facts += (f"communications: {message.get('id')} · Consent: {safety.consent_state.value}", f"Recorded message: {_message(message)}", *safety.decision.evidence)
        contact_id = safety.decision.matched_contact_id
        stop_recorded = any(
            contact_id and (_links(m).get("contact_id") or m.get("contact_id")) == contact_id and _classify(_message(m).casefold(), "", False)[0] == SecretaryIntent.CONSENT_STOP
            for m in records.get("communications", ())
        )
        if stop_recorded or safety.consent_state != ConsentReadState.CONSENT_RECORDED or safety.decision.escalation_required or not safety.decision.draft_response:
            return preview(
                "Draft withheld — review the original communication and consent in Communications.",
                "Existing Nevaeh safety checks require human review.",
                (("A STOP record requires consent investigation." if stop_recorded else safety.decision.escalation_reason), f"Consent: {safety.consent_state.value}"),
            )
        return preview(
            "Thank you for your message. Could you please share an update or clarify what you need next?",
            "A neutral draft based on the selected recorded communication; no unverified facts or promises added.",
            ("Consent is recorded, but channel-specific authorization must still be checked before any future send.",),
        )
    if kind == "Proposed property update":
        prop = entities["property_id"]
        if not prop or property_changes is None:
            return clarify("Identify the property and load its existing property-change evidence first.")
        changes = [c for c in property_changes.changes if c.evidence.property_id == prop.get("id")]
        if not changes:
            return preview("No verified source change is available to propose.", "The recorded detector evidence contains no matching change.")
        if len(changes) != 1:
            return clarify("Which detected property change should I prepare? Review the existing Property Changes queue.")
        patch = prepare_patch(changes[0], prop)
        facts += (f"Detector evidence checked: {property_changes.checked_at}",)
        return preview(
            str({"expected_values": patch.expected_values, "patch": patch.patch}) if not patch.errors else "Update withheld; investigation required.",
            "Existing safe patch validation against current canonical facts. Source must be revalidated before any future Apply.",
            patch.errors,
        )
    if kind == "Owner-approval preparation":
        if not deal:
            return clarify("Which deal's owner approval should I prepare for review?")
        related = _related(deal, records)
        items = build_deal_approval_status(related["offers"], related["documents"])
        return preview(
            "; ".join(i.item_label + ": " + i.next_step for i in items if i.actionable) or "No waiting approval is recorded for this deal.",
            "Existing offer/document approval projection; no decision is made.",
        )
    if kind == "Proposed next action":
        if not deal:
            return clarify("Which deal should I use to prepare its recorded next step?")
        action = build_deal_next_action(dict(deal), _related(deal, records))
        return preview(action.recommended_action, "Recommendation from existing deal tasks and approvals; not completed work.")
    return clarify("Do you want a communication draft, task proposal, property update preview, or next action?")
