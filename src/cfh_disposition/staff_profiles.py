"""Read-only routing over supplied canonical profiles; no provisioning or I/O."""

def configured_members(records):
    return [m for m in records.get("team_members", ()) if m.get("active") is True and m.get("profile")
            and not m.get("archived")]


def resolve_member(name, records):
    key = name.strip().casefold()
    matches = [m for m in configured_members(records) if key in
               {str(m.get(k, "")).casefold() for k in ("name", "id", "email")}]
    return matches[0] if len(matches) == 1 else None


def work_for(member, tasks):
    keys = {str(member.get(k, "")).casefold() for k in ("id", "name", "email")} - {""}
    return [t for t in tasks if not t.get("archived") and str(t.get("status", "")).casefold() not in
            {"done", "completed", "closed", "cancelled"} and
            str(t.get("assigned_to", "")).casefold() in keys]


def route_function(function, records, *, backup_for=None):
    members = configured_members(records)
    if backup_for:
        target = resolve_member(backup_for, records)
        if not target or function not in target["profile"]["functions"]:
            return []
        return [m for m in members if m["profile"].get("universal_staff_backup")
                and m["id"] != target["id"] and m.get("availability") == "available"]
    qualified = [m for m in members if function in m["profile"]["functions"]]
    specialists = [m for m in qualified if not m['profile'].get('universal_staff_backup')]
    available = [m for m in specialists if m.get('availability') == 'available']
    if available:
        return available
    # A backup is a fallback for an existing specialist, not an implicit primary
    # for any function. Operations management is the backup operator's own role.
    return [m for m in qualified if m.get('availability') == 'available'
            and (specialists or function == 'operations_management')]


def requested_functions(text):
    """Recognize work lanes; keep competing meanings for clarification."""
    import re
    text = re.sub(r'\bbuyer[ -]+onboarding\b', 'onboarding', text, flags=re.I)
    patterns = {r"\b(?:title|closing|cfd)\b": 'closing_coordination',
                r"\bonboarding\b": 'buyer_onboarding',
                r"\b(?:sellers?|agents?|fsbo|off.market|acquisitions?|offers?|counteroffers?)\b": 'acquisitions',
                r"\b(?:buyer|showing)\b": 'buyer_followup',
                r"\b(?:social|advertising|ads?|marketing)\b": 'property_marketing',
                r"\b(?:xleads|list (?:import|intake|organization|assignment))\b": 'lead_data_operations',
                r"\b(?:ghl|gohighlevel|crm|automation)\b": 'crm_automation',
                r"\boperations(?: management)?\b": 'operations_management'}
    return {v for k, v in patterns.items() if re.search(k, text, re.I)}
