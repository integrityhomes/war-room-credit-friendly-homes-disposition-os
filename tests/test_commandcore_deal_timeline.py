from copy import deepcopy

from cfh_disposition.commandcore_deal_timeline import (
    build_deal_next_action,
    build_deal_timeline,
)


def related(**updates: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    records: dict[str, list[dict[str, object]]] = {
        "activities": [],
        "communications": [],
        "tasks": [],
        "offers": [],
        "documents": [],
        "transactions": [],
    }
    records.update(updates)
    return records


def test_timeline_uses_existing_records_and_orders_known_dates() -> None:
    records = related(
        communications=[
            {
                "id": "communication-1",
                "direction": "inbound",
                "channel": "sms",
                "summary": "Seller replied",
                "created_at": "2026-09-02T09:00:00Z",
            }
        ],
        tasks=[
            {
                "id": "task-1",
                "title": "Review seller response",
                "status": "completed",
                "completed_at": "2026-09-03T10:00:00Z",
            }
        ],
        offers=[
            {
                "id": "offer-1",
                "status": "draft_pending_owner_approval",
                "created_at": "2026-09-04T11:00:00Z",
            }
        ],
    )

    events = build_deal_timeline({"id": "deal-1", "created_at": "2026-09-01"}, records)

    assert [event.title for event in events] == [
        "Deal created",
        "Communication received",
        "Task completed",
        "Approval requested",
    ]
    assert events[1].detail == "Seller replied"


def test_timeline_deduplicates_same_canonical_record() -> None:
    task = {"id": "task-1", "title": "Follow up", "status": "open", "created_at": "2026-09-02"}

    events = build_deal_timeline({}, related(tasks=[task, dict(task)]))

    assert len(events) == 1
    assert events[0].source_record_id == "task-1"


def test_projection_does_not_mutate_deal_or_related_records() -> None:
    deal = {"id": "deal-1", "stage": "offer review", "assigned_to": "Taylor"}
    records = related(tasks=[{"id": "task-1", "title": "Review offer", "status": "open"}])
    original_deal = deepcopy(deal)
    original_records = deepcopy(records)

    build_deal_timeline(deal, records)
    build_deal_next_action(deal, records)

    assert deal == original_deal
    assert records == original_records


def test_pending_approval_is_protected_and_takes_priority_over_tasks() -> None:
    action = build_deal_next_action(
        {"stage": "offer", "assigned_to": "Deal Owner"},
        related(
            tasks=[{"title": "Routine follow-up", "status": "open", "due_date": "2026-09-20"}],
            offers=[{"status": "draft_pending_owner_approval"}],
        ),
    )

    assert action.current_stage == "Offer"
    assert action.approval_needed is True
    assert action.responsible_person == "Shawn or Sabrina"
    assert "owner" in action.blocker.lower()


def test_next_action_uses_existing_earliest_task_assignment_due_date_and_blocker() -> None:
    action = build_deal_next_action(
        {"stage": "follow_up", "assigned_to": "Deal Owner"},
        related(
            tasks=[
                {"title": "Later", "status": "open", "due_date": "2026-09-20"},
                {
                    "title": "Call seller",
                    "status": "blocked",
                    "due_date": "2026-09-10",
                    "assigned_to": "Sabrina",
                    "blocked_reason": "Waiting for verified facts",
                },
            ]
        ),
    )

    assert action.current_stage == "Follow Up"
    assert action.recommended_action == "Call seller"
    assert action.responsible_person == "Sabrina"
    assert action.due_date == "2026-09-10"
    assert action.blocker == "Waiting for verified facts"
    assert action.approval_needed is False


def test_no_task_fallback_only_recommends_reviewing_recorded_stage() -> None:
    action = build_deal_next_action(
        {"stage": "contract review", "assigned_to": "Shawn"},
        related(),
    )

    assert action.waiting_for == "No open task recorded"
    assert action.recommended_action == "Review the recorded Contract Review stage and choose the next existing workflow."
    assert action.responsible_person == "Shawn"
