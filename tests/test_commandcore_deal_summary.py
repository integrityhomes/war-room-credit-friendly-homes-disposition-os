from cfh_disposition.commandcore_deal_summary import (
    build_deal_summary,
    latest_record,
    next_open_task,
    status_label,
)


def test_next_open_task_prefers_earliest_due_and_skips_completed() -> None:
    tasks = [
        {"title": "Completed", "status": "completed", "due_at": "2026-09-01"},
        {"title": "Later", "status": "open", "due_at": "2026-09-08"},
        {"title": "Next", "status": "open", "due_at": "2026-09-04"},
        {"title": "No date", "status": "open"},
    ]

    assert next_open_task(tasks)["title"] == "Next"


def test_latest_record_is_safe_with_missing_and_invalid_dates() -> None:
    rows = [
        {"summary": "No date"},
        {"summary": "Bad date", "created_at": "not-a-date"},
        {"summary": "Newest", "created_at": "2026-09-03T12:00:00Z"},
        {"summary": "Older", "updated_at": "2026-09-02T12:00:00+00:00"},
    ]

    assert latest_record(rows)["summary"] == "Newest"
    assert latest_record([]) is None


def test_summary_uses_existing_records_for_workflow_statuses_and_approvals() -> None:
    related = {
        "tasks": [
            {"title": "Call seller", "status": "open", "due_at": "2026-09-04"},
            {"work_type": "title_closing", "status": "open", "updated_at": "2026-09-02"},
            {"work_type": "marketing_dispo", "status": "completed", "updated_at": "2026-09-03"},
        ],
        "communications": [{"summary": "Seller replied", "created_at": "2026-09-03"}],
        "activities": [{"summary": "Terms reviewed", "created_at": "2026-09-02"}],
        "offers": [{"status": "draft_pending_owner_approval", "created_at": "2026-09-01"}],
        "documents": [{"status": "internal_review_ready", "created_at": "2026-09-03"}],
        "transactions": [],
    }

    summary = build_deal_summary(related)

    assert summary.next_task["title"] == "Call seller"
    assert summary.recent_communication["summary"] == "Seller replied"
    assert summary.recent_activity["summary"] == "Terms reviewed"
    assert summary.offer["status"] == "draft_pending_owner_approval"
    assert summary.document["status"] == "internal_review_ready"
    assert summary.closing["work_type"] == "title_closing"
    assert summary.marketing["work_type"] == "marketing_dispo"
    assert summary.approval_count == 2


def test_summary_missing_information_has_safe_plain_english_labels() -> None:
    summary = build_deal_summary({})

    assert summary.next_task is None
    assert summary.approval_count == 0
    assert status_label(None) == "Not started"
    assert status_label({}) == "Status not recorded"
    assert status_label({"status": "needs_owner_approval"}) == "Needs Owner Approval"
