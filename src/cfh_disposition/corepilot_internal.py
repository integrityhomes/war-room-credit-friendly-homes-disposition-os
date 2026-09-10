"""Explicit internal commands over existing canonical storage; no outbound executor."""

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from .corepilot_orchestrator import CorePilotResult, run_corepilot

SOURCE = "corepilot-internal"
TIMING = r"\b(tomorrow|today|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|on \d{4}-\d{2}-\d{2})\b"


def due_date(timing, today):
    timing = timing.casefold()
    if timing.startswith("on "):
        return date.fromisoformat(timing[3:]).isoformat()
    offsets = {"today": 0, "tomorrow": 1, "next week": 7}
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    offset = offsets.get(timing)
    if timing in weekdays:
        offset = (weekdays.index(timing) - today.weekday()) % 7
    return (today + timedelta(days=offset)).isoformat() if offset is not None else ""


def create_internal_record(client, entity, record):
    """Same canonical create-only storage pattern as baseline, never upsert."""
    if entity not in {"tasks", "communications", "activities"} or record.get("source") != SOURCE or record.get("internal_only") is not True:
        raise PermissionError("Unsupported internal record")
    if entity == "communications" and (record.get("direction") != "outbound_draft" or record.get("status") != "draft"):
        raise PermissionError("Only private drafts are allowed")
    bucket = client.storage.from_("commandcore-crm-core")
    path = f"{entity}/{record['id']}.json"
    try:
        bucket.upload(path, json.dumps(record, sort_keys=True).encode(), file_options={"content-type": "application/json", "upsert": "false"})
    except Exception:
        # A collision or uncertain response must be verified; never retry an overwrite.
        existing = json.loads(bucket.download(path))
        if existing.get("execution_key") != record["execution_key"] or existing.get("source") != SOURCE:
            raise RuntimeError("Internal action could not be verified") from None
        return False
    existing = json.loads(bucket.download(path))
    if existing != record:
        raise RuntimeError("Internal action could not be verified")
    return True


def run_internal_command(request, records, *, writer, context=None, current_user="", pending=None, today=None, **kwargs):
    """UI runtime boundary. Pure read/preparation remains compatible for other callers."""
    today = today or date.today()
    query = " ".join(request.split()).strip()
    task = re.fullmatch(r"(?:have (.+?) (?:to )?|give (.+?) a task to |make (me) a task to )(follow up|check|review|call|contact)(.*)", query, re.I)
    saving = bool(re.fullmatch(r"save (?:that|the) (?:reply|response) as a draft[.!]?", query, re.I))
    next_action = bool(re.fullmatch(r"(?:prepare|save|record) (?:the |a )?next (?:action|step)(?: for (?:this|the) (?:deal|property))?[.!]?", query, re.I))
    effective = query
    assignee = timing = task_text = ""
    if task:
        assignee = next(x for x in task.groups()[:3] if x)
        if assignee.casefold() == "me":
            assignee = current_user.strip()
        timing_match = re.search(TIMING, task[5], re.I)
        timing = timing_match[0] if timing_match else ""
        task_text = (task[4] + re.sub(TIMING, "", task[5], flags=re.I)).strip(" .")
        # Resolve context independently of the assignee, who may also be a CRM contact.
        effective = "Prepare a task for requested worker to " + task[4] + task[5]
    if saving:
        if not pending or dict(pending.context) != dict(context or {}):
            return CorePilotResult("needs_context", (), (), "Prepare a reply in this context first.",
                                   clarification="Which reply should I save?", context=tuple((context or {}).items()))
        effective = "Draft a reply."
    if next_action:
        effective = "Prepare the next step."
    result = run_corepilot(effective, records, context=context, current_user=current_user, **kwargs)
    action = result.prepared_action
    execute_draft = action and action.what == "Communication draft" and (saving or bool(re.match(r"^(draft|prepare|write)\b", query, re.I)))
    if not (task or next_action or execute_draft) or not action or result.clarification:
        return result
    # Streamlit can retain an older imported enum across source-file reruns.
    # Resolve the current module's category BEFORE any save, never after it.
    from . import corepilot_tools
    internal_class = getattr(corepilot_tools.CorePilotActionClass, "INTERNAL", None)
    if internal_class is None:
        return replace(result, status="safe_failure", prepared_action=None, what_i_found=(),
                       needs_attention=("Command Bot needs an app restart to load its internal-action category. Nothing was saved by this request.",),
                       recommended_next_step="Restart CommandCore, then retry the same command. Duplicate protection remains active.")

    def clarify(message):
        return replace(result, status="needs_context", prepared_action=None, what_i_found=(), needs_attention=(), clarification=message,
                       recommended_next_step="Provide the missing detail; nothing was saved.")

    links = dict(result.context)
    links = {k: v for k, v in links.items() if k in {"property_id", "deal_id", "contact_id"}}
    for key, entity in (("property_id", "properties"), ("deal_id", "deals"), ("contact_id", "contacts")):
        if links.get(key) and not any(r.get("id") == links[key] and not r.get("archived") for r in records.get(entity, ())):
            return clarify("The selected record is no longer available. Select it again.")
    if not links:
        return clarify("Which property, deal, or contact should this relate to?")
    record = {"links": links, "source": SOURCE, "internal_only": True, "external_action_started": False,
              "reason": action.why, "source_facts": list(action.source_facts), "safety_warnings": list(result.needs_attention[1:]),
              "requested_by": current_user or "Authenticated CommandCore user", "request": query}
    if task:
        if not assignee:
            return clarify("What name should I assign your task to? Your signed-in worker name is not set.")
        try:
            due = due_date(timing, today)
        except ValueError:
            return clarify("What valid due date should I use?")
        if not due:
            return clarify("When should this task be due?")
        if re.search(r"\b(and|then|send|approve|sign|pay|delete|publish|apply|transfer|change)\b", task_text, re.I):
            return clarify("Please give me one internal review or follow-up task. Consequential actions remain disabled.")
        entity = "tasks"
        record.update(title=f"{task_text} — {action.subject}", assigned_to=assignee, due_date=due, status="open")
        action = replace(action, assignee=assignee, due_timing=due, why="Internal task requested by you; outreach requires separate consent and authorization.")
        record["reason"] = action.why
        identity = [entity, links, assignee.casefold(), task_text.casefold(), due]
        label = f"Task created: {assignee} — {task_text} · {action.subject} · Due: {due}"
    elif next_action:
        entity = "activities"
        record.update(activity_type="proposed_next_action", title="Proposed next action", summary=action.proposal, status="proposed")
        identity = [entity, links, action.proposal]
        label = f"Next action saved as an internal recommendation: {action.proposal}"
    else:
        if not action.contact_id or not action.communication_id or action.proposal.startswith("Draft withheld"):
            return result
        contact = next((c for c in records.get("contacts", ()) if c.get("id") == action.contact_id and not c.get("archived")), None)
        if not contact:
            return clarify("Which verified recipient should I use?")
        if saving and (pending.prepared_action is None or pending.prepared_action.proposal != action.proposal
                       or pending.prepared_action.communication_id != action.communication_id):
            return clarify("The reply context changed. Review a fresh draft before saving.")
        entity = "communications"
        links["contact_id"] = action.contact_id
        record.update(direction="outbound_draft", status="draft", channel=action.channel, body=action.proposal,
                      reply_to_communication_id=action.communication_id, recipient=contact.get("name") or contact.get("full_name") or action.contact_id,
                      send_enabled=False)
        identity = [entity, links, action.communication_id, action.channel, action.proposal]
        label = f"DRAFT SAVED · Recipient: {record['recipient']} · {action.subject} · Channel: {action.channel} · NOT SENT"
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    now = datetime.now(UTC).isoformat()
    record.update(id="corepilot-" + key, execution_key=key, entity_type=entity, created_at=now, updated_at=now, archived=False)
    if any(r.get("id") == record["id"] for r in records.get(entity, ())):
        created = False
    else:
        try:
            created = writer(entity, record)
        except Exception:
            return replace(result, status="safe_failure", prepared_action=None, what_i_found=(),
                           needs_attention=("The save result could not be verified. Check existing records before retrying; the same request uses duplicate protection.",),
                           recommended_next_step="Review My Work or Communications. Nothing was sent.")
    return replace(result, status="internal_done", what_i_found=(label if created else "Already saved — duplicate prevented.",),
                   needs_attention=tuple(record["safety_warnings"]), recommended_next_step="Review it in My Work, Communications, or the deal timeline. Nothing was sent.",
                   prepared_action=replace(action, status="SAVED INTERNALLY / NOT SENT"), records_written=int(created), action_class=internal_class)
