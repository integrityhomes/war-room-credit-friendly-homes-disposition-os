"""Natural-language staff reads over canonical profiles and My Work."""
import re

from .staff_profiles import configured_members, requested_functions, resolve_member, route_function, work_for


def owner_routing_question(text):
    return bool(re.search(r'\bowner[ -](?:level |approval)|\bapprove\b', text, re.I))


def routing_context(records, context):
    """Resolve only unique canonical IDs and consistent links; never write records."""
    keys = {'task_id': 'tasks', 'deal_id': 'deals', 'property_id': 'properties', 'contact_id': 'contacts'}
    original = dict(context or {})
    resolved = dict(original)
    selected = {}
    while True:
        pending = [key for key in keys if resolved.get(key) and key not in selected]
        if not pending:
            break
        for key in pending:
            matches = [r for r in records.get(keys[key], ()) if r.get('id') == resolved[key] and not r.get('archived')]
            if len(matches) != 1:
                return original, '', 'Which current canonical record should I use?'
            row = selected[key] = matches[0]
            links = row.get('links') or {}
            for linked in keys:
                values = {v for v in (row.get(linked), links.get(linked)) if v}
                if len(values) > 1 or any(resolved.get(linked) and resolved[linked] != value for value in values):
                    return original, '', 'Which record should I use to resolve the conflicting links?'
                if values:
                    resolved[linked] = values.pop()
    # The selected task describes the work; a linked deal's broad stage must not
    # override it. IDs/addresses/person names are never interpreted as work lanes.
    for key in keys:
        if key not in selected:
            continue
        row = selected[key]
        fields = ('title', 'task_type', 'description') if key == 'task_id' else ('next_action', 'stage', 'work_type')
        evidence = ' '.join(str(row.get(field) or '') for field in fields)
        if requested_functions(evidence) or owner_routing_question(evidence):
            return resolved, evidence, ''
        if key == 'task_id':
            break
    return resolved, '', ''


def staff_answer(query, records, context=None):
    from .corepilot_orchestrator import CorePilotResult

    q = query.strip().rstrip('.?!')
    ctx = tuple((context or {}).items())

    def reply(found=(), attention=(), next_step="Review the existing internal work; nothing was sent.", question=""):
        return CorePilotResult('needs_context' if question else 'complete', tuple(found), tuple(attention), next_step,
                               clarification=question, context=ctx)

    members = configured_members(records)
    if q.casefold() in {'show xleads lists', 'show me xleads lists', 'show xleads leads'}:
        found = []
        for entity in ('contacts', 'properties', 'deals'):
            for row in records.get(entity, ()):
                if row.get('archived') or 'xlead' not in str(row.get('source', '')).casefold():
                    continue
                found.append(f"{entity}: {row.get('id')} · Source ID: {row.get('external_id') or 'Not recorded'} · "
                             f"Batch: {row.get('import_batch_name') or row.get('source_file') or 'Not recorded'} · "
                             f"Assigned: {row.get('assigned_to') or 'Unassigned'} · Status: {row.get('status') or 'Not recorded'}")
        return reply(found or ('No XLeads-sourced canonical records are currently recorded.',),
                     (), 'Use the existing CRM import staging, reconciliation and approval path; no list was imported.')
    budget = re.fullmatch(r"what is (.+?)(?:'s|’s) weekly ad budget", q, re.I)
    if budget:
        member = resolve_member(budget[1], records)
        if not member:
            return reply(question="Which configured team member should I use?")
        return reply((f"{member['name']}: no verified current weekly owner-approved budget is available in this view.",),
                     ("No spending is authorized. Unused prior-week budget does not carry forward.",),
                     "Review the existing owner approval and actual spend ledger before any paid-ad execution.")
    workload = re.fullmatch(r"what does (.+?) have today", q, re.I)
    if workload:
        member = resolve_member(workload[1], records)
        if not member:
            return reply(question="That staff profile is not configured. Which verified member should I use?")
        from datetime import date
        tasks = [t for t in work_for(member, records.get('tasks', ())) if
                 str(t.get('due_date') or t.get('due_at') or '')[:10] <= date.today().isoformat()]
        return reply(tuple(f"{t.get('title', 'Internal task')} · Due: {t.get('due_date') or 'Not recorded'}" for t in tasks)
                     or (f"No open work due today or earlier is recorded for {member['name']}.",))
    if q.casefold() == 'who is overloaded':
        found = []
        for m in members:
            count = len(work_for(m, records.get('tasks', ())))
            cap = m.get('profile', {}).get('source', {}).get('capacity_verified')
            found.append(f"{m['name']}: {count} open canonical tasks; " + ("capacity requires review" if not cap else f"recorded capacity {m.get('max_load')}"))
        return reply(found or ('No configured staff profiles are available.',))
    cover = re.fullmatch(r"(.+?) is covering (.+?) today", q, re.I)
    if cover:
        backup, target = resolve_member(cover[1], records), resolve_member(cover[2], records)
        if not backup or not target or not backup['profile'].get('universal_staff_backup'):
            return reply(question="Provide a verified staff member and authorized operational backup.")
        return reply((f"Coverage prepared: {backup['name']} for {target['name']}'s staff operations today.",),
                     ("Owner approval authority does not transfer. Coverage has not been saved.",),
                     "Review this temporary coverage in the existing Coverage screen.")
    if re.search(r"who (?:can cover|should handle|handles)", q, re.I):
        if owner_routing_question(q):
            return reply(('Shawn or Sabrina must make owner-level approval decisions.',),
                         ('Staff delegation and backup never confer owner approval authority.',))
        if re.search(r"cover|someone is out", q, re.I):
            backups = [m for m in members if m['profile'].get('universal_staff_backup') and m.get('availability') == 'available']
            return reply(tuple(f"{m['name']} — {m['profile']['title']}" for m in backups),
                         ('Operational backup does not confer owner approval authority.',))
        functions = requested_functions(q)
        basis = 'the requested work'
        if not functions:
            resolved, evidence, question = routing_context(records, context)
            ctx = tuple(resolved.items())
            if question:
                return reply(question=question)
            if owner_routing_question(evidence):
                return reply(('Shawn or Sabrina must make owner-level approval decisions.',),
                             ('Staff delegation and backup never confer owner approval authority.',))
            functions = requested_functions(evidence)
            basis = 'the selected canonical work and its verified links'
        if not functions:
            return reply(question="Is this buyer follow-up, a closing issue, acquisitions, marketing, or CRM/list work?")
        choices = [route_function(function, records) for function in sorted(functions)]
        candidate_ids = {m['id'] for group in choices for m in group}
        if len(candidate_ids) != 1 or any(not group for group in choices):
            names = sorted({m['name'] for group in choices for m in group})
            return reply(question=(f"Should this go to {' or '.join(names)}?" if len(names) > 1 else
                                   'Which work lane or available specialist should I use?'))
        member = choices[0][0]
        backup = member['profile'].get('universal_staff_backup') and functions != {'operations_management'}
        return reply((f"{member['name']} — {member['profile']['title']}",),
                     ('Operational backup does not confer owner approval authority.',) if backup else (),
                     f"Recommended {'backup because the specialist is unavailable' if backup else 'specialist'} for {basis}. "
                     'Context is retained; no assignment or handoff was saved.')
    profile = re.fullmatch(r"(?:show|review) (.+?)(?:'s|’s) (?:staff )?profile", q, re.I)
    if profile:
        member = resolve_member(profile[1], records)
        if not member:
            return reply(question="That staff profile is not configured.")
        p = member['profile']
        return reply((f"{member['name']} — {p['title']}", *p['responsibilities']), p['approval_limits'])
    return None
