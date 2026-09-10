"""Natural-language staff reads over canonical profiles and My Work."""
import re

from .staff_profiles import configured_members, resolve_member, route_function, work_for


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
        if re.search(r"cover|someone is out", q, re.I):
            backups = [m for m in members if m['profile'].get('universal_staff_backup')]
            return reply(tuple(f"{m['name']} — {m['profile']['title']}" for m in backups),
                         ('Operational backup does not confer owner approval authority.',))
        lanes = {'title': 'closing_coordination', 'closing': 'closing_coordination', 'buyer': 'buyer_followup',
                 'seller': 'acquisitions', 'agent': 'acquisitions', 'social': 'property_marketing',
                 'xleads': 'lead_data_operations', 'automation': 'crm_automation'}
        functions = {v for k, v in lanes.items() if k in q.casefold()}
        if len(functions) != 1:
            return reply(question="Is this buyer follow-up, a closing issue, acquisitions, marketing, or CRM/list work?")
        matches = route_function(functions.pop(), records)
        return reply(tuple(f"{m['name']} — {m['profile']['title']}" for m in matches)
                     or ('No available configured staff member matches this work.',))
    profile = re.fullmatch(r"(?:show|review) (.+?)(?:'s|’s) (?:staff )?profile", q, re.I)
    if profile:
        member = resolve_member(profile[1], records)
        if not member:
            return reply(question="That staff profile is not configured.")
        p = member['profile']
        return reply((f"{member['name']} — {p['title']}", *p['responsibilities']), p['approval_limits'])
    return None
