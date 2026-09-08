"""Validated existing read sources used by the CorePilot registry."""

from __future__ import annotations

from .corepilot_tools import COREPILOT_TOOLS, CorePilotActionClass

# Must mirror the existing commandcore-crm-core ENTITY_TYPES allowlist. CorePilot
# deliberately cannot broaden the service's validation.
CRM_CORE_ENTITIES = frozenset(
    {
        "contacts",
        "properties",
        "deals",
        "activities",
        "communications",
        "tasks",
        "offers",
        "documents",
        "transactions",
    }
)

# Approval views intentionally use the existing offer/document projection. There
# is no standalone approvals entity in commandcore-crm-core.
COREPILOT_READ_SOURCES: dict[str, tuple[str, ...]] = {
    "find_contact": ("contacts",),
    "read_contact": ("contacts",),
    "find_property": ("properties",),
    "read_property": ("properties",),
    "find_deal": ("deals", "properties", "contacts"),
    "read_deal": ("deals", "properties", "contacts"),
    "read_deal_timeline": ("deals", "activities", "communications", "tasks", "offers", "documents", "transactions"),
    "read_current_stage": ("deals",),
    "determine_next_action": ("deals", "tasks", "offers", "documents"),
    "identify_blockers": ("deals", "tasks", "offers", "documents"),
    "read_communications": ("communications", "contacts", "properties", "deals"),
    "summarize_communications": ("communications", "contacts", "properties", "deals"),
    "attention_messages": ("communications", "contacts", "properties", "deals"),
    "consent_messages": ("communications", "contacts", "properties", "deals"),
    "money_legal_messages": ("communications", "contacts", "properties", "deals"),
    "read_assigned_work": ("tasks", "deals"),
    "read_tasks": ("tasks",),
    "overdue_work": ("tasks",),
    "due_today_work": ("tasks",),
    "blocked_work": ("tasks",),
    "read_approvals": ("offers", "documents"),
    "owner_approvals": ("offers", "documents"),
    "approval_status": ("offers", "documents"),
    "read_offer": ("offers", "deals"),
    "read_document_status": ("documents", "deals"),
    "marketing_readiness": ("deals", "properties"),
    "campaign_status": ("deals", "properties"),
    "channel_status": ("deals", "properties"),
    "read_assignments": ("tasks", "deals", "contacts"),
}


def validated_crm_entities() -> tuple[str, ...]:
    """Return required CRM entities, failing closed on an unmapped READ tool."""
    read_keys = {tool.key for tool in COREPILOT_TOOLS if tool.action_class is CorePilotActionClass.READ}
    if read_keys != COREPILOT_READ_SOURCES.keys():
        raise ValueError("corepilot_read_source_registry_incomplete")
    entities = {entity for sources in COREPILOT_READ_SOURCES.values() for entity in sources}
    if not entities <= CRM_CORE_ENTITIES:
        raise ValueError("corepilot_read_source_not_supported")
    return tuple(sorted(entities))
