"""Session context and natural language routes over the existing read projections."""

import re
from dataclasses import replace

from .commandcore_approval_status import build_deal_approval_status
from .commandcore_deal_timeline import _timestamp, build_deal_next_action, build_deal_timeline
from .commandcore_nevaeh_inbox import _message
from .corepilot_orchestrator import CorePilotResult, _find_deals, _find_entities, _label, _links, _related, _run_corepilot, _text, _work_result
from .corepilot_tools import CorePilotActionClass
from .property_change_detection import is_property_change_question, selected_changes


def property_question(query):
    return is_property_change_question(query) or "properties that changed" in query.casefold() or "what changed on it" in query.casefold()


def answer(request, records, *, current_deal_id="", current_user="", property_changes=None, context=None, inventory_evidence=None):
    query = " ".join(request.split())
    lower = query.casefold()
    ctx = dict(context or {})
    from .corepilot_inventory import answer_inventory, inventory_items, inventory_question
    from .corepilot_preparation import preparation_intent, prepare_action
    prepare = bool(preparation_intent(query))
    if not prepare and re.search(r"\b(send|text|call|approve|reject|sign|delete|update|apply|edit|create|pay|spend|publish|deploy|transfer)\b", lower):
        return CorePilotResult(
            "approval_required", (), ("Write, send, and apply actions are disabled here.",), "Ask for a read-only explanation or draft.",
            action_class=CorePilotActionClass.APPROVAL_REQUIRED, context=tuple(ctx.items())
        )

    properties = _find_entities(query, records.get("properties", ()), ("address", "property_address", "name"))
    # Match a verified street component when the canonical address includes city/state.
    if not properties:
        properties = [
            p for p in records.get("properties", ()) if (street := _text(p.get("address") or p.get("property_address")).split(",")[0]) and len(street) > 5 and street.casefold().rstrip(".") in lower
        ]
    deals = _find_deals(query, records)
    contacts = _find_entities(query, records.get("contacts", ()), ("name", "full_name"))
    if len(properties) > 1 or len(deals) > 1 or len(contacts) > 1:
        return CorePilotResult("needs_context", (), (), "Provide a full address or deal name.", clarification="I found more than one matching deal or record. Which one do you mean?")
    if properties or deals or contacts:
        ctx = {}
        if properties:
            ctx["property_id"] = _text(properties[0].get("id"))
            if not deals:
                deals = [d for d in records.get("deals", ()) if _text(_links(d).get("property_id") or d.get("property_id")) == ctx["property_id"]]
        if contacts:
            ctx["contact_id"] = _text(contacts[0].get("id"))
        if len(deals) == 1:
            ctx["deal_id"] = _text(deals[0].get("id"))
            for field in ("property_id", "contact_id"):
                value = _text(_links(deals[0]).get(field) or deals[0].get(field))
                if value:
                    ctx[field] = value
    elif (re.search(r"\b\d+\s+[a-z]", lower) or lower.startswith("find ")) and not inventory_question(query):
        return CorePilotResult("needs_context", (), (), "Provide a recorded full address, deal name, or person.", clarification="Which deal or property do you mean?")
    elif not ctx and current_deal_id:
        ctx["deal_id"] = current_deal_id
    deal = next((d for d in records.get("deals", ()) if d.get("id") == ctx.get("deal_id")), None)
    if deal:
        for field in ("property_id", "contact_id"):
            value = _text(_links(deal).get(field) or deal.get(field))
            if value:
                ctx.setdefault(field, value)

    def finish(result):
        return replace(result, context=tuple(ctx.items()), evidence=result.evidence or tuple(f"{key}: {value}" for key, value in ctx.items()))

    if inventory_question(query):
        return finish(answer_inventory(query, records, ctx, inventory_evidence, property_changes=property_changes))
    if "needs my attention" in lower:
        result = _run_corepilot(query, records, current_user=current_user, property_changes=property_changes)
        stale = [item for item in inventory_items(records.get("properties", ()), inventory_evidence) if item["priority"]]
        unknown = sum(item["days_active"] is None and item["marketing_status"] != "white" for item in inventory_items(records.get("properties", ()), inventory_evidence))
        if stale:
            return finish(replace(result, what_i_found=tuple(x for x in result.what_i_found if x != "You're caught up.")
                                  + tuple(f"{i['address']}: {i['priority']} ({i['age_basis']} for {i['days_active']} days)" for i in stale),
                                  needs_attention=tuple(x for x in result.needs_attention if "Nothing needs" not in x) + (f"{len(stale)} stale properties need review.",),
                                  recommended_next_step="Review the oldest active property and its buyer/marketing evidence. " + result.recommended_next_step.replace("No action is required.", "")))
        if unknown:
            return finish(replace(result, what_i_found=tuple(x for x in result.what_i_found if x != "You're caught up."),
                                  needs_attention=tuple(x for x in result.needs_attention if "Nothing needs" not in x)
                                  + (f"{unknown} properties have unverified marketing age; review yellow highlights and marketing dates.",),
                                  recommended_next_step="Verify missing listing dates before assessing stale inventory. "
                                  + (result.recommended_next_step if not result.recommended_next_step.startswith("No action") else "")))
        return finish(result)
    if prepare:
        return finish(prepare_action(query, records, ctx, property_changes))

    followup = any(t in lower for t in ("this deal", "this property", "this seller", " it", "last", "holding", "waiting on", "do next", "messages", "title company"))
    if property_question(query):
        if property_changes is None:
            return finish(CorePilotResult("needs_context", (), ("Property change evidence is unavailable.",), "Open Property Changes to check the source evidence."))
        changes = selected_changes(query, property_changes)
        if "changed on" in lower:
            if not ctx.get("property_id"):
                return finish(CorePilotResult("needs_context", (), (), "Identify a property first.", clarification="Which property should I review?"))
            changes = tuple(c for c in changes if c.evidence.property_id == ctx["property_id"])
        return finish(
            CorePilotResult(
                "complete",
                tuple(f"{c.evidence.address}: {', '.join(c.categories)}" for c in changes) or ("No matching property changes were detected.",),
                (),
                "Review source evidence in Property Changes. Sheet classification does not verify a closing.",
                evidence=tuple(f"{c.event_id}: {c.evidence.changes}" for c in changes),
            )
        )
    worker = re.search(r"what (?:work does (.+?) have|does (.+?) need to handle)", lower)
    if worker:
        return finish(_work_result("Show my work", records, (worker[1] or worker[2]).strip(" ?.")))
    if "approval" in lower:
        approvals = build_deal_approval_status(list(records.get("offers", ())), list(records.get("documents", ())))
        pending = [a for a in approvals if a.actionable]
        return finish(
            CorePilotResult(
                "complete",
                tuple(a.item_label for a in pending) or ("No recorded approvals are waiting.",),
                (f"{len(pending)} waiting for approval.",),
                "Review waiting items in Owner Approvals; no approval is granted here.",
            )
        )
    if "deals" in lower and "stuck" in lower:
        stuck = []
        for d in records.get("deals", ()):
            action = build_deal_next_action(dict(d), _related(d, records))
            if action.blocker != "No blocker recorded":
                stuck.append(f"{_label(d, 'Deal')}: {action.blocker}")
        return finish(CorePilotResult("complete", tuple(stuck) or ("No recorded deal blockers were found.",), (), "Review the recorded blockers; unrecorded delays cannot be verified."))
    messages = any(t in lower for t in ("conversation", "messages", "title company", "seller say"))
    if messages:
        if not ctx:
            return finish(CorePilotResult("needs_context", (), (), "Identify a deal, property, or contact.", clarification="Whose conversation should I find?"))
        rows = [m for m in records.get("communications", ()) if any(_text(_links(m).get(k) or m.get(k)) == v for k, v in ctx.items() if v)]
        if "seller" in lower or "title company" in lower:
            role = "seller" if "seller" in lower else "title"
            people = {c.get("id") for c in records.get("contacts", ()) if role in " ".join(_text(c.get(k)) for k in ("role", "contact_type", "type", "name", "company")).casefold()}
            rows = [m for m in rows if (_links(m).get("contact_id") or m.get("contact_id")) in people]
        dated = sorted((m for m in rows if _timestamp(dict(m))), key=lambda m: _timestamp(dict(m)), reverse=True)
        if "last" in lower:
            rows = dated[:1]
        else:
            rows = dated + [m for m in rows if not _timestamp(dict(m))]
        ctx.pop("communication_id", None)
        if len(rows) == 1 and rows[0].get("id"):
            ctx["communication_id"] = rows[0]["id"]
        return finish(
            CorePilotResult(
                "complete",
                tuple(_message(m) or "Message body not recorded." for m in rows[:10]) or ("No matching recorded conversation was found.",),
                (),
                "Review the original communication before preparing a response.",
                evidence=tuple(f"communications:{m.get('id')} · {_timestamp(dict(m)) or 'Date not recorded'}" for m in rows[:10]),
            )
        )
    if properties and "find the property" in lower:
        return finish(_run_corepilot(query, records))
    if contacts and not followup:
        return finish(CorePilotResult("complete", (f"Contact: {_label(contacts[0], 'Recorded contact')}",), (), "Ask to see this person's messages."))
    if deal and (followup or deals or properties):
        related = _related(deal, records)
        action = build_deal_next_action(dict(deal), related)
        timeline = build_deal_timeline(dict(deal), related)
        dated = [e for e in timeline if e.occurred_at]
        found = [f"Deal: {_label(deal, 'Recorded deal')}", f"Current stage: {action.current_stage}"]
        if dated:
            found.append(f"Last dated event: {dated[-1].title} — {dated[-1].detail}")
        else:
            found.append("No dated timeline event is recorded.")
        return finish(
            CorePilotResult(
                "complete",
                tuple(found),
                tuple(x for x in (action.waiting_for, action.blocker) if x not in {"No open task recorded", "No blocker recorded"}),
                action.recommended_action,
                evidence=tuple(f"{e.source_entity}:{e.source_record_id} · {e.occurred_at_label} · {e.detail}" for e in timeline),
            )
        )
    if properties or (ctx.get("property_id") and followup):
        p = next((p for p in records.get("properties", ()) if p.get("id") == ctx.get("property_id")), {})
        return finish(
            CorePilotResult(
                "complete",
                (f"Property: {_label(p, 'Recorded property')}",),
                ("No unique linked deal is selected; closing progress cannot be verified.",),
                "Identify a linked deal to review closing tasks or blockers.",
            )
        )
    if contacts:
        return finish(CorePilotResult("complete", (f"Contact: {_label(contacts[0], 'Recorded contact')}",), (), "Ask to see this person's messages or identify a linked deal."))
    return finish(_run_corepilot(query, records, current_deal_id=ctx.get("deal_id", ""), current_user=current_user, property_changes=property_changes))
