"""Internal task management and private draft revisions in canonical CRM records."""

import hashlib
import json
import re
from datetime import UTC, date, datetime
from threading import RLock

from .corepilot_orchestrator import CorePilotResult

_lock = RLock()
ALLOWED = {"tasks": {"status", "due_date", "assigned_to", "internal_notes"}, "communications": {"body"}}


def payload(value):
    if isinstance(value, (bytes, bytearray)):
        value = json.loads(value)
    if not isinstance(value, dict) or not value.get("ok"):
        raise ValueError("Canonical operation failed")
    return value


def update_internal_record(client, entity, expected, patch, actor):
    """Re-read before patching; keep before/after history in the existing record."""
    if entity not in ALLOWED or not patch or not patch.keys() <= ALLOWED[entity]:
        raise PermissionError("Unsupported internal patch")
    if expected.get("archived") or expected.get("internal_only") is not True:
        raise PermissionError("Only existing internal records can be managed")
    if entity == "communications" and (expected.get("direction") != "outbound_draft" or expected.get("status") != "draft"):
        raise PermissionError("Only unsent private drafts can be revised")
    if "status" in patch and patch["status"] != "done":
        raise PermissionError("Unsupported status change")
    body = {"entity": entity, "id": expected["id"]}
    with _lock:
        current = payload(client.functions.invoke("commandcore-crm-core", {"body": {**body, "action": "get"}}))["record"]
        if current != expected:
            raise ValueError("Record changed; read it again before retrying")
        changes = {k: {"old": current.get(k), "new": v} for k, v in patch.items() if current.get(k) != v}
        if not changes:
            return False
        history = list(current.get("internal_history", []))
        history.append({"at": datetime.now(UTC).isoformat(), "actor": actor or "Authenticated CommandCore user",
                        "changes": changes, "source": "corepilot-work"})
        outgoing = {"id": current["id"], **patch, "internal_history": history}
        payload(client.functions.invoke("commandcore-crm-core", {"body": {"entity": entity, "action": "upsert", "record": outgoing}}))
        saved = payload(client.functions.invoke("commandcore-crm-core", {"body": {**body, "action": "get"}}))["record"]
        if any(saved.get(k) != v for k, v in outgoing.items()):
            raise ValueError("Saved result could not be verified")
        return True


def manage_work(query, records, context, updater, *, current_user="", today=None):
    """Return None for unrelated commands; retain selected IDs, never hidden data copies."""
    from . import corepilot_tools
    from .corepilot_internal import due_date

    internal_class = getattr(corepilot_tools.CorePilotActionClass, "INTERNAL", None)

    q = query.strip().rstrip(".?!")
    ctx = dict(context or {})
    work = re.fullmatch(r"what work does (.+?) have", q, re.I)
    select = re.fullmatch(r"(?:select|review) task (.+)", q, re.I)
    move = re.fullmatch(r"(?:move|reschedule) (?:that|it|this task) to (.+)", q, re.I)
    assign = re.fullmatch(r"(?:give|reassign) (?:it|that|this|this task) to (.+)", q, re.I)
    note = re.fullmatch(r"add (?:a )?note(?: that)? (.+)", q, re.I)
    done = re.fullmatch(r"(?:mark (?:it|that|this task) (?:done|complete)|complete (?:it|that|this task))", q, re.I)
    retrieve = re.fullmatch(r"(?:show|retrieve|open) (?:my |the |that )?(?:private )?draft(?: (.+))?", q, re.I)
    revise = re.fullmatch(r"(?:revise|replace) (?:that |the )?draft(?: with| to|:)\s+(.+)", q, re.I)
    empty_note = bool(re.fullmatch(r"add (?:a )?note", q, re.I))
    if not any((work, select, move, assign, note, empty_note, done, retrieve, revise)):
        return None

    def answer(text, *, question="", changed=0, evidence=()):
        return CorePilotResult("complete" if not question else "needs_context", (text,) if text else (), (),
                               "Internal work only. Nothing was sent.", clarification=question, context=tuple(ctx.items()),
                               records_written=changed, evidence=tuple(evidence), **({"action_class": internal_class} if changed else {}))

    entity = "communications" if retrieve or revise else "tasks"
    rows = [r for r in records.get(entity, ()) if not r.get("archived")]
    if entity == "communications":
        rows = [r for r in rows if r.get("internal_only") is True and r.get("direction") == "outbound_draft" and r.get("status") == "draft"]
    key = "draft_id" if entity == "communications" else "task_id"
    if work or select or retrieve:
        ctx.pop(key, None)
        if work:
            rows = [r for r in rows if str(r.get("assigned_to", "")).casefold() == work[1].casefold()
                    and r.get("status") not in {"done", "completed", "closed", "cancelled"}]
        elif select:
            rows = [r for r in rows if select[1].casefold() in {str(r.get("id", "")).casefold(), str(r.get("title", "")).casefold()}]
        elif retrieve[1]:
            rows = [r for r in rows if r.get("id") == retrieve[1]]
        else:
            rows = [r for r in rows if all((r.get("links") or {}).get(k) == v for k, v in ctx.items() if k in {"property_id", "deal_id", "contact_id"})]
        if len(rows) != 1:
            listing = "\n".join(f"{r.get('title') or 'Private draft'} · ID: {r['id']}" for r in rows)
            return answer(listing or "No matching internal records.", question="Which task or draft should I select? Use its exact title or ID." if rows else "")
        selected = rows[0]
        ctx = {k: v for k, v in (selected.get("links") or {}).items() if k in {"property_id", "deal_id", "contact_id"}}
        ctx[key] = selected["id"]
        return answer(selected.get("body", "") + " · PRIVATE DRAFT / NOT SENT. Verify user revisions and consent before any future use." if retrieve else
                      f"{selected.get('title')} · {selected.get('assigned_to')} · Due: {selected.get('due_date')} · Status: {selected.get('status')}",
                      evidence=(json.dumps(selected.get("internal_history", [])),))
    selected = next((r for r in rows if r.get("id") == ctx.get(key)), None)
    if empty_note:
        return answer("", question="What should the private note say?" if selected else "Which task should the note belong to?")
    if not selected:
        return answer("", question="Which existing internal task or private draft should I use? Select it first.")
    if selected.get("internal_only") is not True:
        return answer("", question="This record is not verified as internal-only. Review it in My Work before making changes.")
    if any((selected.get("links") or {}).get(k) != v for k, v in ctx.items() if k in {"property_id", "deal_id", "contact_id"}):
        ctx.pop(key, None)
        return answer("", question="The selected work belongs to a different context. Select it again.")
    patch = {}
    if move:
        try:
            due = due_date(move[1], today or date.today())
        except ValueError:
            due = ""
        if not due:
            return answer("", question="Which valid date should I use?")
        patch = {"due_date": due}
    elif assign:
        from .staff_profiles import resolve_member
        if 'team_members' in records:
            member = resolve_member(assign[1], records)
            from .staff_profiles import requested_function
            function = requested_function(selected.get('title', ''))
            if member and function and function not in member['profile']['functions'] and not member['profile'].get('universal_staff_backup'):
                return answer('', question='That work is outside this staff profile. Choose an authorized worker or approved backup.')
            matches = [member['name']] if member else []
        else:  # Backward-compatible isolated callers without the registry adapter.
            names = {str(r.get(k)).strip() for group in records.values() for r in group for k in ("assigned_to", "assigned_worker") if r.get(k)}
            matches = [n for n in names if n.casefold() == assign[1].casefold()]
        if len(matches) != 1:
            return answer("", question="Which verified CommandCore assignee should I use? That name is not uniquely recorded in current assignments.")
        patch = {"assigned_to": matches[0]}
    elif done:
        patch = {"status": "done"}
    elif note:
        notes = list(selected.get("internal_notes", []))
        key_hash = hashlib.sha256(note[1].encode()).hexdigest()
        if any(n.get("id") == key_hash for n in notes):
            return answer("That private note is already saved.")
        notes.append({"id": key_hash, "text": note[1], "author": current_user or "Authenticated CommandCore user", "at": datetime.now(UTC).isoformat()})
        patch = {"internal_notes": notes}
    elif revise:
        # User-supplied copy is retained as a private, unverified draft, never sent.
        patch = {"body": revise[1]}
    if updater is None:
        return answer("", question="Internal work updates are unavailable in this runtime.")
    if internal_class is None:
        return answer("Restart CommandCore to load its internal-action category. Nothing was saved.")
    try:
        changed = updater(entity, selected, patch, current_user)
    except Exception:
        return answer("The save could not be verified. Read the record again before retrying; nothing was sent.")
    if assign:
        ctx["assignee"] = patch["assigned_to"]
    return answer("DONE — internal record updated." if changed else "Already recorded — no duplicate change.", changed=int(changed),
                  evidence=(json.dumps({"before": {k: selected.get(k) for k in patch}, "proposed": patch}),))
