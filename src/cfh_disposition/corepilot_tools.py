"""Canonical registry of existing CommandCore capabilities exposed to CorePilot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CorePilotActionClass(StrEnum):
    READ = "READ"
    PREPARE = "PREPARE"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


@dataclass(frozen=True, slots=True)
class CorePilotTool:
    key: str
    display_name: str
    description: str
    entity_types: tuple[str, ...]
    required_context: tuple[str, ...]
    required_inputs: tuple[str, ...]
    action_class: CorePilotActionClass
    mutates_commandcore: bool
    performs_external_action: bool
    required_approval_level: str
    safe_failure_behavior: str
    source_engine: str


def _read(key: str, name: str, description: str, entities: tuple[str, ...], source: str, *, context: tuple[str, ...] = (), inputs: tuple[str, ...] = ()) -> CorePilotTool:
    return CorePilotTool(
        key, name, description, entities, context, inputs, CorePilotActionClass.READ, False, False, "None", "Ask for one missing detail or report that no verified record was found.", source
    )


def _prepare(key: str, name: str, description: str, source: str) -> CorePilotTool:
    return CorePilotTool(
        key,
        name,
        description,
        ("Deal",),
        ("Deal",),
        ("Request",),
        CorePilotActionClass.PREPARE,
        False,
        False,
        "Owner approval before consequential execution",
        "Stop if the deal is missing or ambiguous; create a preview only.",
        source,
    )


COREPILOT_TOOLS: tuple[CorePilotTool, ...] = (
    _read("find_contact", "Find contact", "Find an existing contact.", ("Contact",), "CommandCore CRM", inputs=("Name or other identifying detail",)),
    _read("read_contact", "Read contact details", "Show recorded contact details.", ("Contact",), "CommandCore CRM", context=("Contact",)),
    _read("find_property", "Find property", "Find an existing property.", ("Property",), "CommandCore CRM", inputs=("Address or identifying detail",)),
    _read("read_property", "Read property details", "Show verified property facts already recorded.", ("Property",), "CommandCore CRM", context=("Property",)),
    _read("find_deal", "Find deal", "Find an existing deal.", ("Deal", "Property", "Contact"), "CommandCore CRM", inputs=("Deal, property, or contact detail",)),
    _read("read_deal", "Read deal", "Show an existing deal and its linked records.", ("Deal",), "CommandCore CRM", context=("Deal",)),
    _read(
        "read_deal_timeline",
        "Read deal timeline",
        "Show the canonical deal history.",
        ("Deal", "Communication", "Task", "Offer", "Document", "Transaction"),
        "commandcore_deal_timeline",
        context=("Deal",),
    ),
    _read("read_current_stage", "Read current stage", "Show the recorded deal stage.", ("Deal",), "CommandCore CRM", context=("Deal",)),
    _read(
        "determine_next_action",
        "Determine known next action",
        "Use recorded work and approvals to explain the next step.",
        ("Deal", "Task", "Approval"),
        "commandcore_deal_timeline",
        context=("Deal",),
    ),
    _read("identify_blockers", "Identify blockers", "Show blockers already recorded on work or approvals.", ("Deal", "Task", "Approval"), "commandcore_deal_timeline", context=("Deal",)),
    _read("read_communications", "Read communications", "Read existing inbound communication records.", ("Communication",), "commandcore_nevaeh_inbox"),
    _read("summarize_communications", "Summarize communications", "Summarize classified inbound communications.", ("Communication",), "commandcore_nevaeh_inbox"),
    _read("attention_messages", "Identify messages needing attention", "Show messages Nevaeh marked for review.", ("Communication",), "commandcore_nevaeh_inbox"),
    _read("consent_messages", "Identify STOP or consent messages", "Keep consent-related messages prominent.", ("Communication",), "commandcore_nevaeh_inbox"),
    _read("money_legal_messages", "Identify money or legal messages", "Keep protected money and legal messages prominent.", ("Communication",), "commandcore_nevaeh_inbox"),
    _read("read_assigned_work", "Read assigned work", "Show work assigned to a recorded team member.", ("Task", "Deal"), "CommandCore CRM", inputs=("Team member when not current user",)),
    _read("read_tasks", "Read tasks", "Show existing tasks.", ("Task",), "CommandCore CRM"),
    _read("overdue_work", "Identify overdue work", "Show incomplete work past its recorded due date.", ("Task",), "CommandCore CRM"),
    _read("due_today_work", "Identify work due today", "Show incomplete work due today.", ("Task",), "CommandCore CRM"),
    _read("blocked_work", "Identify blocked work", "Show tasks recorded as blocked.", ("Task",), "CommandCore CRM"),
    _read("read_approvals", "Read approvals", "Show existing approval records.", ("Approval", "Offer", "Document"), "commandcore_approval_status"),
    _read("owner_approvals", "Identify owner approvals", "Show work waiting for owner review.", ("Approval", "Offer", "Document"), "commandcore_approval_status"),
    _read("approval_status", "Read approval status", "Show the current recorded approval state.", ("Approval",), "commandcore_approval_status"),
    _read("read_offer", "Read offer information", "Show recorded offer information.", ("Offer", "Deal"), "CommandCore CRM", context=("Deal",)),
    _prepare("prepare_offer", "Prepare an offer", "Prepare an internal offer-work preview without sending it.", "command_agent / task_agent simulation"),
    _read("read_document_status", "Read document status", "Show recorded document and contract status.", ("Document", "Deal"), "CommandCore CRM", context=("Deal",)),
    _prepare("prepare_contract", "Prepare contract information", "Prepare an internal contract-work preview without signing or sending it.", "command_agent / task_agent simulation"),
    _read("marketing_readiness", "Read marketing readiness", "Show recorded marketing readiness.", ("Deal", "Property"), "CommandCore marketing engines", context=("Deal",)),
    _read("campaign_status", "Read campaign status", "Show recorded campaign status.", ("Deal", "Property"), "CommandCore marketing engines", context=("Deal",)),
    _read("channel_status", "Read channel launch status", "Show existing channel status records.", ("Deal", "Property"), "CommandCore marketing engines", context=("Deal",)),
    _prepare("prepare_marketing", "Prepare marketing work", "Prepare an internal marketing handoff preview without publishing or spending.", "command_agent / task_agent simulation"),
    _read("read_assignments", "Read assignment information", "Show existing staff and deal assignments.", ("Deal", "Task", "Contact"), "CommandCore CRM"),
    CorePilotTool(
        "send_communication",
        "Send a communication",
        "Protected outbound communication capability.",
        ("Communication", "Contact"),
        ("Contact",),
        ("Approved content", "Valid consent"),
        CorePilotActionClass.APPROVAL_REQUIRED,
        True,
        True,
        "Required communication and owner gates",
        "Never execute in CorePilot Phase 1; direct the user to the protected workflow.",
        "Nevaeh communication gates",
    ),
    CorePilotTool(
        "record_owner_decision",
        "Record an owner decision",
        "Protected owner approval capability.",
        ("Approval",),
        ("Approval",),
        ("Owner decision",),
        CorePilotActionClass.APPROVAL_REQUIRED,
        True,
        False,
        "Authorized owner",
        "Never execute in CorePilot Phase 1; open Owner Approvals for review.",
        "CommandCore Owner Approvals",
    ),
)

COREPILOT_TOOL_REGISTRY = {tool.key: tool for tool in COREPILOT_TOOLS}


def get_corepilot_tool(key: str) -> CorePilotTool | None:
    return COREPILOT_TOOL_REGISTRY.get(key)
