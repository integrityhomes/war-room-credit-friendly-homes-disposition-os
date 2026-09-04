from datetime import date, datetime

import pytest

from cfh_disposition.commandcore_followup import MAX_FOLLOWUP_NOTE_LENGTH, build_followup_record


def test_shared_followup_record_preserves_deal_owner_and_internal_boundary() -> None:
    record = build_followup_record(
        deal_id="deal-123",
        note=" Call seller about inspection ",
        due=datetime(2026, 9, 8, 14, 30),
        assigned_to="Alex",
    )

    assert record["title"] == "Call seller about inspection"
    assert record["due_at"] == "2026-09-08T14:30"
    assert record["assigned_to"] == "Alex"
    assert record["task_type"] == "crm_follow_up"
    assert record["links"] == {"deal_id": "deal-123"}
    assert record["internal_only"] is True
    assert record["external_action_started"] is False


def test_shared_followup_record_keeps_pipeline_date_contract() -> None:
    record = build_followup_record(
        deal_id="deal-123",
        note="Review seller response",
        due=date(2026, 9, 9),
    )

    assert record["due_date"] == "2026-09-09"
    assert "due_at" not in record
    assert record["assigned_to"] is None


def test_identical_followup_submission_has_deterministic_external_id() -> None:
    values = {
        "deal_id": "deal-123",
        "note": "Review seller response",
        "due": datetime(2026, 9, 9, 9, 0),
        "assigned_to": "Alex",
    }

    assert build_followup_record(**values)["external_id"] == build_followup_record(**values)["external_id"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"deal_id": ""}, "Deal is required"),
        ({"note": "   "}, "follow-up note"),
        ({"note": "x" * (MAX_FOLLOWUP_NOTE_LENGTH + 1)}, "characters or fewer"),
    ],
)
def test_shared_followup_record_rejects_missing_or_unsafe_input(overrides: dict, message: str) -> None:
    values = {
        "deal_id": "deal-123",
        "note": "Review seller response",
        "due": datetime(2026, 9, 9, 9, 0),
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        build_followup_record(**values)
