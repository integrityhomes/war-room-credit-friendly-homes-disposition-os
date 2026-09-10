"""Profiles and routing in the existing private team registry, never a second roster.

Authority describes delegation; it does not enable an external executor or authenticate
an owner. Original questionnaires remain private evidence in the canonical member.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field

BUCKET = "commandcore-team-registry"


class StaffProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    responsibilities: list[str] = Field(min_length=1)
    functions: list[str] = Field(min_length=1)
    systems: list[str]
    communication_authority: str
    approval_limits: list[str]
    escalation: list[str] = Field(min_length=1)
    handoffs: dict[str, list[str]]
    prohibited_actions: list[str] = Field(min_length=1)
    universal_staff_backup: bool = False
    owner_approval_authority: bool = False
    pronouns: str = ""
    source: dict
    questionnaire: str = Field(min_length=100)
    source_review: list[dict] = Field(default_factory=list)
    unresolved_details: list[str] = Field(default_factory=list)


def read_team(client):
    bucket = client.storage.from_(BUCKET)
    rows = bucket.list("members", {"limit": 1000})
    if len(rows) >= 1000:
        raise ValueError("Complete team registry unavailable")
    members = [json.loads(bucket.download("members/" + r["name"])) for r in rows if r.get("name", "").endswith(".json")]
    ids = [m.get("id") for m in members]
    if not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("Team identity needs review")
    return members


def create_profile(client, member, *, preservation_verified=False):
    """Create-only canonical provisioning, gated on the compatible registry service.

    Call only from an owner-authorized provisioning operation, never a bot read.
    No schema creation, upsert, credential change, or external action is present.
    """
    if not preservation_verified:
        raise PermissionError('Registry profile preservation must be verified before activation')
    StaffProfile.model_validate(member['profile'])
    if member['profile'].get('owner_approval_authority'):
        raise PermissionError('Staff provisioning cannot grant owner approval authority')
    if not member.get('email') or not member.get('id') or not member.get('name'):
        raise ValueError('Verified staff identity is required')
    if any(c in member['id'] for c in ('/', '\\', '..')):
        raise ValueError('Unsafe member identity')
    matches = [m for m in read_team(client) if any(str(m.get(k, '')).casefold() == str(member[k]).casefold()
                                                for k in ('id', 'email', 'name'))]
    if matches:
        if len(matches) == 1 and matches[0] == member:
            return False
        raise ValueError('Existing staff identity or profile differs; review before changing it')
    bucket = client.storage.from_(BUCKET)
    path = f"members/{member['id']}.json"
    try:
        bucket.upload(path, json.dumps(member, sort_keys=True).encode(), file_options={'content-type': 'application/json', 'upsert': 'false'})
    except Exception:
        if json.loads(bucket.download(path)) == member:
            return False
        raise ValueError('Profile save could not be verified; no overwrite attempted') from None
    if json.loads(bucket.download(path)) != member:
        raise ValueError('Profile verification failed')
    return True


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
    return [m for m in members if function in m["profile"]["functions"] and m.get("availability") == "available"]


def requested_function(text):
    import re
    patterns = {r"\b(?:title|closing|cfd)\b": 'closing_coordination',
                r"\b(?:seller|agent|fsbo|off.market)\b": 'acquisitions',
                r"\b(?:buyer|showing)\b": 'buyer_followup',
                r"\b(?:social|advertising|ad)\b": 'property_marketing',
                r"\b(?:xleads|list import)\b": 'lead_data_operations',
                r"\b(?:ghl|crm automation)\b": 'crm_automation'}
    matches = {v for k, v in patterns.items() if re.search(k, text, re.I)}
    return next(iter(matches)) if len(matches) == 1 else None


def handoff_targets(member, event, records):
    """Resolve declared staff handoffs; deferred names never become assignees."""
    names = member.get('profile', {}).get('handoffs', {}).get(event, ())
    return [target for name in names if (target := resolve_member(name, records))]


def delegation_check(member, function, *, owner_consequential=False, facts_verified=False,
                     consent_verified=False, within_approved_rules=False):
    """Evaluate preparation eligibility only; external execution is always disabled."""
    profile = StaffProfile.model_validate(member["profile"])
    # Broad staff access is a declared set of staff functions, not a wildcard
    # granting unknown or consequential functions to a backup operator.
    eligible = member.get("active") is True and function in profile.functions
    if owner_consequential:
        return {"eligible": False, "external_execution": False, "reason": "Owner approval required"}
    if function in {"buyer_communication", "title_communication", "seller_communication"}:
        eligible = eligible and facts_verified and consent_verified and within_approved_rules
    if function == "offer_preparation":
        eligible = eligible and facts_verified and within_approved_rules
    return {"eligible": eligible, "external_execution": False,
            "reason": "Delegated preparation; external execution remains disabled" if eligible else "Missing authority or verified evidence; escalate"}


def weekly_budget_status(evidence, *, today=None, proposed_spend=0):
    """Read an existing budget approval/ledger projection. Never create an approval.

    Expiration is explicit; an old approval or unknown spend cannot imply capacity.
    The caller must obtain approval_verified from the canonical approval system.
    """
    today = today or date.today()
    blocked = {"approved": None, "spent": None, "remaining": None, "percent": None,
               "level": "Owner-approved weekly budget not verified", "new_spend_allowed": False}
    try:
        start, end = date.fromisoformat(evidence["week_start"]), date.fromisoformat(evidence["week_end"])
        if not evidence.get("approval_verified") or not start <= today <= end or (end-start).days != 6:
            return blocked
        cap, spent, proposed = (Decimal(str(v)) for v in (evidence["approved_amount"], evidence["spent"], proposed_spend))
        if not all(v.is_finite() for v in (cap, spent, proposed)) or cap <= 0 or spent < 0 or proposed < 0:
            return blocked
    except (KeyError, ValueError, InvalidOperation, TypeError):
        return blocked
    percent = spent / cap * 100
    level = "Blocked — additional owner approval required" if percent >= 100 else "High-priority warning" if percent >= 90 else "Warning" if percent >= 75 else "Within approved weekly budget"
    return {"approved": str(cap), "spent": str(spent), "remaining": str(max(Decimal(0), cap-spent)),
            "percent": str(percent), "level": level, "new_spend_allowed": spent < cap and spent+proposed <= cap}
