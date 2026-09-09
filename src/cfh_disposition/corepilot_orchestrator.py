"""Pure, read-only orchestration over canonical CommandCore records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .command_agent import dispatch_command, is_dev_command, parse_ops_intent
from .commandcore_deal_timeline import build_deal_next_action, build_deal_timeline
from .commandcore_nevaeh_inbox import NevaehInboxCategory, build_nevaeh_inbox
from .corepilot_tools import CorePilotActionClass, get_corepilot_tool


@dataclass(frozen=True, slots=True)
class CorePilotResult:
    status: str
    what_i_found: tuple[str, ...]
    needs_attention: tuple[str, ...]
    recommended_next_step: str
    clarification: str = ""
    capability_names: tuple[str, ...] = ()
    action_class: CorePilotActionClass = CorePilotActionClass.READ
    records_written: int = 0
    external_actions_started: int = 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _links(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("links")
    return value if isinstance(value, Mapping) else {}


def _label(record: Mapping[str, Any], fallback: str) -> str:
    return _text(record.get("title") or record.get("name") or record.get("address") or record.get("property_address")) or fallback


def _linked(record: Mapping[str, Any], deal_id: str) -> bool:
    return _text(_links(record).get("deal_id") or record.get("deal_id")) == deal_id


def _find_deals(query: str, records: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[Mapping[str, Any]]:
    needle = query.casefold()
    properties = {_text(item.get("id")): item for item in records.get("properties", ())}
    contacts = {_text(item.get("id")): item for item in records.get("contacts", ())}
    matches: list[Mapping[str, Any]] = []
    for deal in records.get("deals", ()):
        links = _links(deal)
        related = [properties.get(_text(links.get("property_id") or deal.get("property_id")), {}), contacts.get(_text(links.get("contact_id") or deal.get("contact_id")), {})]
        candidates = [_label(deal, ""), *(_label(item, "") for item in related)]
        # Display names must not hide the canonical address embedded in a request.
        candidates.extend(_text(item.get(field)) for item in (deal, related[0]) for field in ("address", "property_address"))
        if any(candidate and len(candidate) >= 3 and candidate.casefold() in needle for candidate in candidates):
            matches.append(deal)
    return matches


def _find_entities(
    request: str,
    records: Sequence[Mapping[str, Any]],
    fields: tuple[str, ...],
) -> list[Mapping[str, Any]]:
    needle = request.casefold()
    return [record for record in records if any((value := _text(record.get(field))) and len(value) >= 3 and value.casefold() in needle for field in fields)]


def _related(deal: Mapping[str, Any], records: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    deal_id = _text(deal.get("id"))
    return {entity: [dict(item) for item in records.get(entity, ()) if _linked(item, deal_id)] for entity in ("activities", "communications", "tasks", "offers", "documents", "transactions")}


def _tool_names(*keys: str) -> tuple[str, ...]:
    return tuple(tool.display_name for key in keys if (tool := get_corepilot_tool(key)))


def _choose_deal(request: str, records: Mapping[str, Sequence[Mapping[str, Any]]], current_deal_id: str) -> tuple[Mapping[str, Any] | None, str]:
    matches = _find_deals(request, records)
    if len(matches) == 1:
        return matches[0], ""
    if len(matches) > 1:
        return None, "I found more than one matching deal. Which property or seller do you mean?"
    if current_deal_id:
        current = next((deal for deal in records.get("deals", ()) if _text(deal.get("id")) == current_deal_id), None)
        if current:
            return current, ""
    return None, "Which deal or property do you mean?"


def _work_result(request: str, records: Mapping[str, Sequence[Mapping[str, Any]]], current_user: str) -> CorePilotResult:
    lower = request.casefold()
    owner = current_user
    if "assigned work" in lower and "show me" in lower:
        between = lower.split("show me", 1)[1].split("assigned work", 1)[0].strip(" 's")
        owner = between or current_user
    open_tasks = [task for task in records.get("tasks", ()) if _text(task.get("status")).casefold() not in {"done", "completed", "closed", "cancelled", "canceled"}]
    if owner:
        open_tasks = [task for task in open_tasks if owner.casefold() in _text(task.get("assigned_to") or task.get("assigned_worker")).casefold()]
    today = date.today().isoformat()
    overdue = [task for task in open_tasks if (due := _text(task.get("due_date") or task.get("due_at"))) and due[:10] < today]
    due_today = [task for task in open_tasks if _text(task.get("due_date") or task.get("due_at"))[:10] == today]
    blocked = [task for task in open_tasks if _text(task.get("status")).casefold() == "blocked" or _text(task.get("blocker") or task.get("blocked_reason"))]
    found = tuple(_label(task, "Untitled task") for task in open_tasks[:12]) or ("No open assigned work was found.",)
    attention = tuple([f"{len(overdue)} overdue", f"{len(due_today)} due today", f"{len(blocked)} blocked"])
    return CorePilotResult("complete", found, attention, "Review the most urgent recorded task.", capability_names=_tool_names("read_assigned_work", "overdue_work", "due_today_work", "blocked_work"))


def _communications_result(records: Mapping[str, Sequence[Mapping[str, Any]]], current_user: str) -> CorePilotResult:
    items = build_nevaeh_inbox(
        records.get("communications", ()), contacts=records.get("contacts", ()), properties=records.get("properties", ()), deals=records.get("deals", ()), assigned_to=current_user
    )
    attention = [item for item in items if NevaehInboxCategory.NEEDS_REVIEW in item.categories]
    stop = [item for item in items if NevaehInboxCategory.STOP_CONSENT in item.categories]
    protected = [item for item in items if NevaehInboxCategory.MONEY_LEGAL in item.categories]
    found = (f"{len(items)} inbound communications are available.",)
    needs = (f"{len(attention)} need attention.", f"{len(stop)} include STOP or consent concerns.", f"{len(protected)} involve money or legal topics.")
    return CorePilotResult(
        "complete",
        found,
        needs,
        "Open Communications and review protected items first.",
        capability_names=_tool_names("summarize_communications", "attention_messages", "consent_messages", "money_legal_messages"),
    )


def _attention_result(
    records: Mapping[str, Sequence[Mapping[str, Any]]],
    current_user: str,
) -> CorePilotResult:
    open_tasks = [
        task
        for task in records.get("tasks", ())
        if _text(task.get("status")).casefold() not in {"done", "completed", "closed", "cancelled", "canceled"}
        and (not current_user or current_user.casefold() in _text(task.get("assigned_to") or task.get("assigned_worker")).casefold())
    ]
    today = date.today().isoformat()
    overdue = sum(bool(due := _text(task.get("due_date") or task.get("due_at"))) and due[:10] < today for task in open_tasks)
    due_today = sum(_text(task.get("due_date") or task.get("due_at"))[:10] == today for task in open_tasks)
    blocked = sum(_text(task.get("status")).casefold() == "blocked" or bool(_text(task.get("blocker") or task.get("blocked_reason"))) for task in open_tasks)
    inbox = build_nevaeh_inbox(
        records.get("communications", ()),
        contacts=records.get("contacts", ()),
        properties=records.get("properties", ()),
        deals=records.get("deals", ()),
        assigned_to=current_user,
    )
    stop_consent = sum(NevaehInboxCategory.STOP_CONSENT in item.categories for item in inbox)
    money_legal = sum(NevaehInboxCategory.MONEY_LEGAL in item.categories for item in inbox)
    communications = sum(NevaehInboxCategory.NEEDS_REVIEW in item.categories for item in inbox)
    owner_approvals = sum(
        1
        for entity in ("offers", "documents")
        for item in records.get(entity, ())
        if "approval" in _text(item.get("status")).casefold() or _text(item.get("status")).casefold() in {"pending", "requested"}
    )

    counts = (
        (stop_consent, "STOP / consent communication", "Review the STOP / consent communication first."),
        (money_legal, "money / legal communication", "Review the money / legal communication first."),
        (owner_approvals, "owner approval", "Review the waiting owner approval first."),
        (overdue, "overdue task", "Review the overdue task first."),
        (due_today, "task due today", "Review the task due today first."),
        (blocked, "blocked task", "Review the blocked task first."),
        (communications, "communication needing attention", "Review the communication needing attention first."),
    )
    actionable = [(count, label, recommendation) for count, label, recommendation in counts if count > 0]
    capabilities = _tool_names(
        "read_assigned_work",
        "overdue_work",
        "due_today_work",
        "blocked_work",
        "attention_messages",
        "consent_messages",
        "money_legal_messages",
        "owner_approvals",
    )
    if not actionable:
        return CorePilotResult(
            "complete",
            ("You're caught up.",),
            ("Nothing needs your attention right now.",),
            "No action is required. CorePilot will surface new work here when something needs attention.",
            capability_names=capabilities,
        )
    found = tuple(f"{count} {label}{'' if count == 1 else 's'}" for count, label, _ in actionable)
    return CorePilotResult(
        "complete",
        found,
        (f"{sum(count for count, _, _ in actionable)} actionable items need attention.",),
        actionable[0][2],
        capability_names=capabilities,
    )


def run_corepilot(request: str, records: Mapping[str, Sequence[Mapping[str, Any]]], *, current_deal_id: str = "", current_user: str = "") -> CorePilotResult:
    """Answer from supplied canonical records without mutation or external execution."""
    query = " ".join(request.split())
    lower = query.casefold()
    if not query:
        return CorePilotResult("needs_context", (), (), "Enter a request to begin.", clarification="What do you need?")
    if is_dev_command(query):
        return CorePilotResult("approval_required", (), ("CorePilot cannot modify source code.",), "Use the separate development workflow.", action_class=CorePilotActionClass.APPROVAL_REQUIRED)
    if any(term in lower for term in ("send ", "text ", "call ", "approve ", "reject ", "sign ", "port ", "cancel number")):
        return CorePilotResult(
            "approval_required",
            (),
            ("That action requires a protected workflow and cannot run here.",),
            "Open the related protected page for review.",
            capability_names=_tool_names("send_communication", "record_owner_decision"),
            action_class=CorePilotActionClass.APPROVAL_REQUIRED,
        )
    if "communication" in lower or "message" in lower or "inbox" in lower:
        return _communications_result(records, current_user)
    if "needs my attention" in lower:
        return _attention_result(records, current_user)
    if "my work" in lower or "assigned work" in lower or "overdue" in lower or "due today" in lower:
        return _work_result(query, records, current_user)
    if "approval" in lower:
        related = [
            item
            for entity in ("offers", "documents")
            for item in records.get(entity, ())
            if "approval" in _text(item.get("status")).casefold() or _text(item.get("status")).casefold() in {"pending", "requested"}
        ]
        return CorePilotResult("complete", (f"{len(related)} recorded items are waiting for approval.",), (), "Open Owner Approvals to review them.", capability_names=_tool_names("owner_approvals"))

    if "contact" in lower or "seller" in lower or "buyer" in lower:
        matches = _find_entities(query, records.get("contacts", ()), ("name", "full_name", "first_name", "last_name"))
        if len(matches) != 1:
            question = "I found more than one matching contact. Which person do you mean?" if matches else "Which contact do you mean?"
            return CorePilotResult("needs_context", (), (), "Provide one identifying detail.", clarification=question, capability_names=_tool_names("find_contact"))
        return CorePilotResult(
            "complete",
            (f"Contact: {_label(matches[0], 'Recorded contact')}",),
            (),
            "Open Leads to review the full existing record.",
            capability_names=_tool_names("find_contact", "read_contact"),
        )

    if "property" in lower and not any(term in lower for term in ("deal", "next step", "timeline", "block")):
        matches = _find_entities(query, records.get("properties", ()), ("address", "property_address", "name"))
        if len(matches) != 1:
            question = "I found more than one matching property. Which address do you mean?" if matches else "Which property address do you mean?"
            return CorePilotResult("needs_context", (), (), "Provide one identifying detail.", clarification=question, capability_names=_tool_names("find_property"))
        return CorePilotResult(
            "complete",
            (f"Property: {_label(matches[0], 'Recorded property')}",),
            (),
            "Open the linked deal to review its verified facts.",
            capability_names=_tool_names("find_property", "read_property"),
        )

    if "deals" in lower and "no next action" in lower:
        missing = []
        for deal in records.get("deals", ()):
            projection = build_deal_next_action(dict(deal), _related(deal, records))
            if projection.waiting_for == "No open task recorded" and not projection.approval_needed:
                missing.append(_label(deal, "Recorded deal"))
        return CorePilotResult(
            "complete",
            tuple(missing) or ("Every recorded deal has an existing task or approval next step.",),
            (f"{len(missing)} deals have no recorded next action.",),
            "Review these deals and choose the next existing workflow.",
            capability_names=_tool_names("determine_next_action"),
        )

    intent = parse_ops_intent(query)
    deal_terms = ("deal", "property", "closing", "next step", "timeline", "block", "offer", "contract", "marketing")
    if intent or any(term in lower for term in deal_terms) or _find_deals(query, records):
        deal, question = _choose_deal(query, records, current_deal_id)
        if not deal:
            return CorePilotResult("needs_context", (), (), "Provide one identifying detail.", clarification=question, capability_names=_tool_names("find_deal"))
        deal_name = _label(deal, "Selected deal")
        related = _related(deal, records)
        next_action = build_deal_next_action(dict(deal), related)
        if intent in {"prepare_offer", "prepare_contract", "marketing_dispo"}:
            run = dispatch_command(command=query, deal=dict(deal))
            if run.status != "simulated" or not run.task_agent_runs:
                return CorePilotResult("safe_failure", (), ("The preparation preview could not be created safely.",), "Review the deal and try again.", action_class=CorePilotActionClass.PREPARE)
            key = {"prepare_offer": "prepare_offer", "prepare_contract": "prepare_contract", "marketing_dispo": "prepare_marketing"}[intent]
            return CorePilotResult(
                "prepared",
                (f"A private preview is ready for {deal_name}.",),
                ("Nothing was saved, sent, approved, signed, published, or purchased.",),
                "Review the deal before using its protected workflow.",
                capability_names=_tool_names(key),
                action_class=CorePilotActionClass.PREPARE,
            )
        timeline = build_deal_timeline(dict(deal), related)
        found = (f"Deal: {deal_name}", f"Current stage: {next_action.current_stage}", f"{len(timeline)} recorded timeline events")
        attention = tuple(item for item in (next_action.waiting_for, next_action.blocker) if item and item not in {"No blocker recorded", "No open task recorded"})
        return CorePilotResult(
            "complete", found, attention, next_action.recommended_action, capability_names=_tool_names("read_deal", "read_deal_timeline", "determine_next_action", "identify_blockers")
        )

    return CorePilotResult("needs_context", (), (), "Try one of the quick actions or name a deal, message, task, or approval.", clarification="What would you like CorePilot to find or explain?")
