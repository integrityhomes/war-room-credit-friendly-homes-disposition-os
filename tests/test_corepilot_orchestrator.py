from cfh_disposition.corepilot_orchestrator import run_corepilot
from cfh_disposition.corepilot_tools import CorePilotActionClass


def _records() -> dict[str, list[dict[str, object]]]:
    return {
        "contacts": [{"id": "contact-fictional", "name": "Avery Example"}],
        "properties": [{"id": "property-fictional", "address": "101 Example Lane"}],
        "deals": [{"id": "deal-fictional", "title": "Example Lane deal", "stage": "closing", "links": {"property_id": "property-fictional", "contact_id": "contact-fictional"}}],
        "tasks": [
            {
                "id": "task-fictional",
                "title": "Confirm fictional title update",
                "status": "blocked",
                "blocked_reason": "Waiting for recorded title update",
                "assigned_to": "Sabrina",
                "links": {"deal_id": "deal-fictional"},
            }
        ],
        "communications": [],
        "approvals": [],
        "offers": [],
        "documents": [],
        "transactions": [],
        "activities": [],
    }


def test_read_request_uses_current_deal_context_without_mutation() -> None:
    records = _records()
    before = repr(records)
    result = run_corepilot("What is the next step on this deal?", records, current_deal_id="deal-fictional")
    assert result.status == "complete"
    assert "Confirm fictional title update" in result.recommended_next_step
    assert result.records_written == 0
    assert result.external_actions_started == 0
    assert repr(records) == before


def test_ambiguous_deal_fails_closed_with_one_question() -> None:
    records = _records()
    records["deals"].append({"id": "deal-fictional-2", "title": "Example Lane deal"})
    result = run_corepilot("Find the Example Lane deal", records)
    assert result.status == "needs_context"
    assert result.clarification.endswith("?")
    assert result.records_written == 0


def test_prepare_is_preview_only_and_external_action_is_zero() -> None:
    result = run_corepilot("Prepare an offer for 101 Example Lane", _records())
    assert result.status == "prepared"
    assert result.action_class is CorePilotActionClass.PREPARE
    assert result.records_written == 0
    assert result.external_actions_started == 0
    assert "Nothing was saved" in result.needs_attention[0]


def test_consequential_request_stops_before_execution() -> None:
    result = run_corepilot("Send a text to Avery", _records())
    assert result.status == "approval_required"
    assert result.action_class is CorePilotActionClass.APPROVAL_REQUIRED
    assert result.records_written == 0
    assert result.external_actions_started == 0


def test_find_contact_reads_only_canonical_contact() -> None:
    result = run_corepilot("Find the Avery Example contact", _records())
    assert result.status == "complete"
    assert result.what_i_found == ("Contact: Avery Example",)
    assert result.records_written == 0


def test_deals_without_next_action_are_derived_without_creating_tasks() -> None:
    records = _records()
    records["deals"].append({"id": "deal-no-task", "title": "Fictional quiet deal"})
    result = run_corepilot("Which deals have no next action?", records)
    assert result.status == "complete"
    assert "Fictional quiet deal" in result.what_i_found
    assert result.records_written == 0
