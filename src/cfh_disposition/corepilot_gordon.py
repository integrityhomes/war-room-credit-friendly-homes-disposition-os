"""Opt-in local inspection through the existing Gordon adapter; no CRM transport."""

import importlib.util
import re
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Fixed source-only observations. Neither prompts nor CRM context choose paths.
INSPECTIONS = {
    "integration": "src/cfh_disposition/commandcore_integrations.py",
    "connector": "src/cfh_disposition/external_app_integration.py",
    "automation": "src/cfh_disposition/corepilot_tools.py",
    "system": "pyproject.toml",
    "maintenance": "pyproject.toml",
}


class GordonJob(BaseModel):
    """Caller retains this identity across retries; never regenerate on rerender."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    idempotency_key: UUID
    correlation_id: UUID


def existing_adapter(checkout, inspection_root, journal):
    """Explicit host configuration only; never called automatically by the UI.

    Load Gordon under its own namespace to avoid CommandCore's app.py collision.
    The owner-reviewed checkout supplies all execution and durable job policy.
    """
    package = Path(checkout).resolve(strict=True) / "app"
    name = "_commandcore_existing_gordon"
    if name in sys.modules:
        if Path(sys.modules[name].__file__).resolve() != package / "__init__.py":
            raise ValueError("A different Gordon checkout is already loaded")
    else:
        spec = importlib.util.spec_from_file_location(name, package / "__init__.py", submodule_search_locations=[str(package)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    from importlib import import_module

    return import_module(name + ".local_adapter").LocalGordonAdapter(inspection_root, journal)


class GordonConnection:
    """Thin transport boundary; Gordon owns job IDs, audit and duplicate control."""

    def __init__(self, adapter):
        self.adapter = adapter

    def inspect(self, lane, job):
        if lane not in INSPECTIONS or not isinstance(job, GordonJob):
            raise ValueError("A supported lane and stable job identity are required")
        outcome = self.adapter.submit({
            "job_type": "technical.inspect",
            "steps": [{"command": "read", "path": INSPECTIONS[lane]}],
            "timeout_seconds": 10.0,
            "idempotency_key": str(job.idempotency_key),
            "correlation_id": str(job.correlation_id),
        })
        # Fail closed on an unavailable/mismatched protocol; never display raw errors.
        required = {"accepted", "job_id", "correlation_id", "status", "result", "error", "actions_attempted", "approvals_required", "audit", "cost"}
        if not isinstance(outcome, dict) or set(outcome) != required:
            raise ValueError("Invalid Gordon response")
        UUID(outcome["job_id"])
        if outcome["correlation_id"] != str(job.correlation_id) or type(outcome["accepted"]) is not bool:
            raise ValueError("Invalid Gordon correlation")
        if outcome["status"] not in {"rejected", "approval_required", "blocked", "running", "completed", "failed", "timed_out"}:
            raise ValueError("Unknown Gordon status")
        if not isinstance(outcome["actions_attempted"], list) or not isinstance(outcome["approvals_required"], list):
            raise ValueError("Invalid Gordon actions")
        audit = outcome["audit"]
        if type(audit["durable"]) is not bool:
            raise ValueError("Invalid Gordon audit")
        if audit["durable"]:
            UUID(audit["event_id"])
        if outcome["cost"] != {"api_calls": 0, "models": [], "cost_usd": 0.0}:
            raise ValueError("Non-local Gordon outcome")
        if outcome["status"] == "completed" and (not outcome["accepted"] or not audit["durable"] or outcome["error"] is not None):
            raise ValueError("Unverified Gordon completion")
        return deepcopy(outcome)


def technical_lane(request):
    text = " ".join(request.casefold().split())
    patterns = {
        "integration": r"\bintegration (?:troubleshooting|diagnostics)\b|\btroubleshoot (?:the |an )?integration\b",
        "connector": r"\bconnector health(?: checks?)?\b|\bcheck (?:the )?connector\b",
        "automation": r"\b(?:approved )?automation diagnostics\b|\bdiagnose (?:the |an )?automation\b",
        "system": r"\bsystem diagnostics\b|\bdiagnose (?:the )?system\b",
        "maintenance": r"\b(?:supported )?technical maintenance\b",
    }
    lanes = [lane for lane, pattern in patterns.items() if re.search(pattern, text)]
    return lanes[0] if len(lanes) == 1 else "ambiguous" if lanes else None


def gordon_answer(request, connection=None, job=None):
    from .corepilot_orchestrator import CorePilotResult
    from .corepilot_tools import CorePilotActionClass
    from .staff_profiles import requested_functions

    lane = technical_lane(request)
    if lane is None:
        return None
    capability = ("Gordon local technical inspection",)
    # Prompt claims of approval never grant authority or become executable plans.
    if re.search(r"\b(send|text|call|approve|reject|sign|delete|update|apply|edit|create|pay|spend|publish|deploy|transfer|install|execute|repair|fix)\b", request, re.I):
        return CorePilotResult("approval_required", ("Technical work belongs with Gordon.",),
                               ("Only Shawn and Sabrina have owner-level approval authority. Execution is blocked.",),
                               "Request a bounded read-only inspection for review.", capability_names=capability,
                               action_class=CorePilotActionClass.APPROVAL_REQUIRED)
    clauses = re.split(r"\band\b|\bthen\b|;", request, flags=re.I)
    mixed_business = any(technical_lane(clause) is None and requested_functions(clause) for clause in clauses)
    if lane == "ambiguous" or mixed_business:
        return CorePilotResult("needs_context", (), (), "Select one bounded technical inspection.",
                               clarification="Which single technical check should Gordon inspect? Keep staff work in its existing workflow.", capability_names=capability)
    if connection is None or job is None:
        return CorePilotResult("prepared", ("Route technical inspection to Gordon, the technical specialist under CorePilot.",),
                               ("Live Gordon execution is disabled; local source inspection does not establish connector health.",),
                               "Review the local Gordon connection and supply a stable job identity before inspection.", capability_names=capability)
    try:
        outcome = connection.inspect(lane, job)
    except Exception:
        return CorePilotResult("safe_failure", (), ("The local Gordon connection failed; execution outcome may be unknown.",),
                               "Inspect Gordon's existing journal; retain the same job identity for any retry.", capability_names=capability)
    return CorePilotResult(outcome["status"], (f"Gordon job {outcome['job_id']}: {outcome['status']}",),
                           ("Local source inspection only; remote connector health is unverified.",),
                           "Review Gordon's correlated result in CommandCore; no business action is authorized.",
                           capability_names=capability, gordon_outcome=outcome,
                           evidence=(f"gordon_job:{outcome['job_id']}", f"correlation:{outcome['correlation_id']}",
                                     f"gordon_audit:{outcome['audit']['event_id']}"))
