"""Deterministic review ordering over verified, existing read projections."""

import re
from datetime import date

from .canonical_work_view import CLOSED
from .commandcore_approval_status import build_deal_approval_status
from .commandcore_nevaeh_inbox import NevaehInboxCategory, build_nevaeh_inbox
from .corepilot_inventory import inventory_items
from .corepilot_orchestrator import CorePilotResult, _label, _links, _related


def priority_question(query):
    return bool(re.fullmatch(
        r"(?:what should (?:we|my team) work on first|what is the most important thing right now|"
        r"prioritize today['’]s work|what needs to happen first)[?.!]*", query.strip(), re.I))


def priority_answer(records, property_changes=None, inventory_evidence=None, *, today=None):
    from .commandcore_deal_timeline import build_deal_next_action

    today = today or date.today()
    records = {k: [r for r in group if not r.get("archived")] for k, group in records.items()}
    rows = []

    def add(rank, key, label, reason, links):
        ctx = {k: v for k, v in links.items() if k in {"property_id", "deal_id", "contact_id"} and v}
        rows.append((rank, key, label, reason, ctx))

    inbox = build_nevaeh_inbox(records.get("communications", ()), contacts=records.get("contacts", ()),
                               properties=records.get("properties", ()), deals=records.get("deals", ()))
    for item in inbox:
        urgent = NevaehInboxCategory.STOP_CONSENT in item.categories or NevaehInboxCategory.MONEY_LEGAL in item.categories
        if urgent or NevaehInboxCategory.NEEDS_REVIEW in item.categories:
            source = next(r for r in records.get("communications", ()) if r.get("id") == item.communication_id)
            add(0 if urgent else 7, f"communication:{item.communication_id}", item.person,
                "STOP/consent or money/legal communication requires human review" if urgent else "Communication needs a response review", _links(source))
    for entity in ("offers", "documents"):
        for r in records.get(entity, ()):
            approvals = build_deal_approval_status([r] if entity == "offers" else [], [r] if entity == "documents" else [])
            if any(a.actionable for a in approvals):
                add(1, f"{entity}:{r.get('id')}", _label(r, "Owner approval"), "Owner approval is waiting; no approval is performed", _links(r))
    for item in inventory_items(records.get("properties", ()), inventory_evidence, today=today):
        if item["priority"]:
            add(2 if item["days_active"] >= 21 else 6, f"property:{item['property_id']}", item["address"],
                f"{item['age_basis']} for {item['days_active']} days — stale inventory review", {"property_id": item["property_id"]})
    for r in records.get("deals", ()):
        if r.get("archived"):
            continue
        action = build_deal_next_action(dict(r), _related(r, records))
        if action.blocker and action.blocker != "No blocker recorded":
            add(3, f"deal:{r.get('id')}", _label(r, "Recorded deal"), f"Recorded blocker: {action.blocker}", {**_links(r), "deal_id": r.get("id")})
    for r in records.get("tasks", ()):
        if r.get("archived") or str(r.get("status", "")).casefold() in CLOSED:
            continue
        try:
            due = date.fromisoformat(str(r.get("due_date") or r.get("due_at"))[:10])
        except ValueError:
            due = None
        reason = "Overdue task" if due and due < today else "Task due today" if due == today else ""
        if r.get("blocker") or r.get("blocked_reason") or r.get("status") == "blocked":
            reason = reason or "Blocked task"
        if reason:
            add(4 if due and due < today else 5, f"task:{r.get('id')}", _label(r, "Recorded task"),
                f"{reason} · Assigned to: {r.get('assigned_to') or 'Unassigned'}", _links(r))
    if property_changes:
        for c in property_changes.changes:
            add(2 if c.priority.casefold() in {"urgent", "high", "critical"} else 6, f"change:{c.event_id}", c.evidence.address,
                f"Source change needs review: {', '.join(c.categories)}; source status does not prove closing", {"property_id": c.evidence.property_id})
    rows.sort(key=lambda r: (r[0], r[1]))
    if not rows:
        return CorePilotResult("complete", ("Nothing in the available verified records requires attention right now.",), (),
                               "No action is required.")
    top = rows[0]
    ctx = top[4]
    return CorePilotResult("complete", tuple(f"{i}. {r[2]} — {r[3]}" for i, r in enumerate(rows, 1)),
                           ("Ranking is a recommended review order based on recorded evidence, not an authorization to act.",),
                           f"Review item 1: {top[2]}." + (" This is the selected follow-up context." if ctx else " Identify its linked property or deal before preparing a follow-up."),
                           context=tuple(ctx.items()), evidence=tuple(r[1] for r in rows))
