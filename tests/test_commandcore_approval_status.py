from cfh_disposition.commandcore_approval_status import build_deal_approval_status


def test_pending_offer_and_document_are_actionable_without_request_timestamp() -> None:
    items = build_deal_approval_status(
        [{"status": "draft_pending_owner_approval", "amount": 125000}],
        [{"status": "owner_approval_required", "name": "Purchase agreement"}],
    )

    assert [item.state for item in items] == ["Waiting for approval", "Waiting for approval"]
    assert all(item.actionable for item in items)
    assert all(not item.decided_at for item in items)
    assert items[0].item_label == "Offer recommendation — $125,000"


def test_explicit_owner_decisions_show_supported_history() -> None:
    items = build_deal_approval_status(
        [
            {
                "status": "owner_approved",
                "owner_approved_by": "Shawn",
                "owner_decided_at": "2026-09-03T12:30:00Z",
            }
        ],
        [
            {
                "status": "owner_rejected",
                "owner_rejected_by": "Sabrina",
                "owner_decided_at": "2026-09-04T09:00:00Z",
                "owner_decision_reason": "Terms need revision.",
            }
        ],
    )

    assert [(item.state, item.decided_by) for item in items] == [
        ("Rejected", "Sabrina"),
        ("Approved", "Shawn"),
    ]
    assert items[0].decision_reason == "Terms need revision."
    assert not any(item.actionable for item in items)


def test_legal_template_blocker_needs_attention_but_cannot_be_reviewed() -> None:
    items = build_deal_approval_status([], [{"status": "needs_approved_legal_template"}])

    assert len(items) == 1
    assert items[0].state == "Needs attention"
    assert not items[0].actionable
    assert "approved legal template" in items[0].next_step


def test_generic_or_incomplete_records_do_not_invent_approval_states() -> None:
    items = build_deal_approval_status(
        [{"status": "draft"}, {}],
        [{"status": "completed"}, {"status": "draft"}, {}],
    )

    assert items == []


def test_owner_approval_status_supports_existing_decision_field() -> None:
    items = build_deal_approval_status(
        [{"status": "draft", "owner_approval_status": "owner_approved", "owner_approved_by": "Shawn"}],
        [],
    )

    assert len(items) == 1
    assert items[0].state == "Approved"
    assert items[0].decided_by == "Shawn"


def test_current_queue_status_takes_priority_over_stale_decision_field() -> None:
    items = build_deal_approval_status(
        [{"status": "draft_pending_owner_approval", "owner_approval_status": "owner_rejected"}],
        [],
    )

    assert len(items) == 1
    assert items[0].state == "Waiting for approval"
    assert items[0].actionable
