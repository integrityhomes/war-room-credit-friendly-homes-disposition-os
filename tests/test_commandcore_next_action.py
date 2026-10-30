from __future__ import annotations

from cfh_disposition.commandcore_lead_flow import (
    APPROVED_OFFER_STATUS,
    MARKETING_STAGE,
    PENDING_OFFER_STATUS,
)
from cfh_disposition.commandcore_next_action import (
    STATUS_CLOSED,
    STATUS_MARKETING_LIVE,
    STATUS_NEEDS_APPROVAL,
    STATUS_NEEDS_TERMS,
    STATUS_READY_TO_MARKET,
    next_action,
)


def test_new_lead_needs_terms() -> None:
    action = next_action({"id": "d1", "stage": "New Lead", "status": "Active"})
    assert action.status == STATUS_NEEDS_TERMS
    assert action.key == "needs_terms"
    assert "Deal" in action.action_page


def test_terms_without_approval_request() -> None:
    action = next_action(
        {
            "id": "d2",
            "stage": "Analyzing",
            "status": "Active",
            "asking_price": "149900",
            "offer_price": "135000",
        }
    )
    assert action.status == STATUS_NEEDS_APPROVAL
    assert action.key == "needs_approval_request"


def test_pending_offer_needs_approval() -> None:
    action = next_action(
        {
            "id": "d3",
            "stage": "Offer Pending",
            "status": "Active",
            "asking_price": "149900",
            "offer_price": "135000",
        },
        offers=[
            {
                "id": "o1",
                "status": PENDING_OFFER_STATUS,
                "links": {"deal_id": "d3"},
            }
        ],
    )
    assert action.status == STATUS_NEEDS_APPROVAL
    assert action.key == "needs_approval"
    assert "Owner_Approvals" in action.action_page


def test_approved_offer_ready_to_market() -> None:
    action = next_action(
        {
            "id": "d4",
            "stage": "Offer Made",
            "status": "Active",
            "asking_price": "149900",
            "offer_price": "135000",
        },
        offers=[
            {
                "id": "o2",
                "status": APPROVED_OFFER_STATUS,
                "links": {"deal_id": "d4"},
            }
        ],
    )
    assert action.status == STATUS_READY_TO_MARKET
    assert action.key == "ready_to_market"


def test_marketing_live() -> None:
    action = next_action(
        {
            "id": "d5",
            "stage": MARKETING_STAGE,
            "status": "Active",
            "marketing_status": "ready_internal",
        },
        offers=[{"id": "o3", "status": APPROVED_OFFER_STATUS, "links": {"deal_id": "d5"}}],
    )
    assert action.status == STATUS_MARKETING_LIVE
    assert action.key == "marketing_live"


def test_closed_deal() -> None:
    action = next_action({"id": "d6", "stage": "Closed", "status": "Closed"})
    assert action.status == STATUS_CLOSED
    assert action.key == "closed"
