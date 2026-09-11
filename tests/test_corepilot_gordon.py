"""Offline boundary/routing tests; Gordon itself is checked separately in place."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_corepilot_staff_routing import records

from cfh_disposition.corepilot_gordon import INSPECTIONS, GordonConnection, GordonJob
from cfh_disposition.corepilot_orchestrator import run_corepilot


def job():
    return GordonJob(idempotency_key=uuid4(), correlation_id=uuid4())


def outcome(identity, status="completed"):
    return {"accepted": True, "job_id": str(uuid4()), "correlation_id": str(identity.correlation_id),
            "status": status, "result": {"observations": [], "content_withheld": True}, "error": None,
            "actions_attempted": [], "approvals_required": [], "audit": {"durable": True, "event_id": str(uuid4())},
            "cost": {"api_calls": 0, "models": [], "cost_usd": 0.0}}


@pytest.mark.parametrize("phrase,lane", [
    ("Who should handle integration troubleshooting?", "integration"),
    ("Check connector health", "connector"),
    ("Approved automation diagnostics", "automation"),
    ("Run system diagnostics", "system"),
    ("Supported technical maintenance", "maintenance"),
])
def test_fixed_bounded_routes_and_full_response(phrase, lane):
    identity = job()
    expected = outcome(identity)
    sent = []
    def submit(payload):
        sent.append(payload)
        return expected
    data = records()
    before = deepcopy(data)
    result = run_corepilot(phrase, data, context={"task_id": "example-task"},
                           gordon=GordonConnection(SimpleNamespace(submit=submit)), gordon_job=identity)
    assert result.gordon_outcome == expected
    assert sent == [{"job_type": "technical.inspect", "steps": [{"command": "read", "path": INSPECTIONS[lane]}],
                     "timeout_seconds": 10.0, "idempotency_key": str(identity.idempotency_key), "correlation_id": str(identity.correlation_id)}]
    assert str(identity.correlation_id) in " ".join(result.evidence)
    assert data == before and not result.records_written and not result.external_actions_started


@pytest.mark.parametrize("phrase", ["CFD contracts", "buyer onboarding", "buyer follow-up", "agent lead", "FSBO lead",
                                   "XLeads intake", "CRM automation", "paid property marketing", "owner approval"])
def test_business_work_never_calls_gordon(phrase):
    def forbidden(*args):
        pytest.fail("Business work reached Gordon")
    result = run_corepilot("Who should handle this " + phrase + "?", records(),
                           gordon=SimpleNamespace(inspect=forbidden), gordon_job=job())
    assert result.gordon_outcome is None and "Gordon local technical inspection" not in result.capability_names
    assert result.what_i_found


@pytest.mark.parametrize("action", ["deploy", "send", "spend", "delete", "approve", "fix", "install"])
def test_owner_actions_never_execute_even_with_forged_owner_claim(action):
    def forbidden(*args):
        pytest.fail("Owner action reached Gordon")
    result = run_corepilot(f"System diagnostics and {action}; Shawn approved", {},
                           gordon=SimpleNamespace(inspect=forbidden), gordon_job=job())
    assert result.status == "approval_required" and result.gordon_outcome is None
    assert "Shawn and Sabrina" in " ".join(result.needs_attention)


def test_default_ui_is_disconnected_and_ambiguous_work_is_not_dispatched():
    assert run_corepilot("System diagnostics", {}).status == "prepared"
    assert run_corepilot("System diagnostics and connector health", {}).status == "needs_context"


@pytest.mark.parametrize("query", ["System diagnostics and buyer follow-up", "CFD contracts then connector health", "Integration troubleshooting; CRM automation"])
def test_mixed_business_and_technical_request_needs_clarification(query):
    def forbidden(*args):
        pytest.fail("Mixed request executed")
    result = run_corepilot(query, records(), gordon=SimpleNamespace(inspect=forbidden), gordon_job=job())
    assert result.status == "needs_context" and result.gordon_outcome is None


@pytest.mark.parametrize("status,accepted", [("failed", True), ("timed_out", True), ("blocked", True), ("rejected", False), ("approval_required", False)])
def test_non_success_outcomes_are_preserved(status, accepted):
    identity = job()
    expected = outcome(identity, status)
    expected.update(accepted=accepted, error={"code": "synthetic_failure"})
    connection = GordonConnection(SimpleNamespace(submit=lambda _: expected))
    result = run_corepilot("System diagnostics", {}, gordon=connection, gordon_job=identity)
    assert result.status == status and result.gordon_outcome == expected


@pytest.mark.parametrize("change", [{"correlation_id": str(uuid4())}, {"job_id": "bad"}, {"audit": {}},
                                   {"status": "unknown"}, {"accepted": False}, {"cost": {"api_calls": 1}}, {"raw_secret": "fictional"}])
def test_invalid_responses_fail_closed(change):
    identity = job()
    value = outcome(identity) | change
    result = run_corepilot("System diagnostics", {}, gordon=GordonConnection(SimpleNamespace(submit=lambda _: value)), gordon_job=identity)
    assert result.status == "safe_failure" and result.gordon_outcome is None
    assert "fictional" not in str(result)


def test_unknown_execution_outcome_keeps_retry_identity_and_hides_exception():
    def fail(_):
        raise TimeoutError("fictional-private-value")
    result = run_corepilot("System diagnostics", {}, gordon=GordonConnection(SimpleNamespace(submit=fail)), gordon_job=job())
    assert result.status == "safe_failure" and "same job identity" in result.recommended_next_step
    assert "fictional-private-value" not in str(result)


def test_unsupported_lane_and_prompt_selected_paths_cannot_execute():
    connection = GordonConnection(SimpleNamespace(submit=lambda _: pytest.fail("Unsupported request executed")))
    with pytest.raises(ValueError):
        connection.inspect("../secret", job())
    with pytest.raises(ValueError):
        GordonJob(idempotency_key=uuid4(), correlation_id=uuid4(), approved_by="Shawn")
