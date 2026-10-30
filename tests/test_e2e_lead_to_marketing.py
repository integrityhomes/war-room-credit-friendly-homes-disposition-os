"""End-to-end Leads → Deal → Approval → Marketing on the demo CRM backend."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cfh_disposition.commandcore_crm_client import reset_crm_clients_for_tests
from cfh_disposition.commandcore_crm_demo import DemoCrmBackend
from cfh_disposition.commandcore_lead_flow import (
    APPROVED_OFFER_STATUS,
    MARKETING_STAGE,
    PENDING_OFFER_STATUS,
    create_lead,
    grant_approval,
    publish_marketing,
    request_approval,
    set_deal_terms,
)
from cfh_disposition.commandcore_next_action import (
    STATUS_MARKETING_LIVE,
    STATUS_NEEDS_APPROVAL,
    STATUS_NEEDS_TERMS,
    STATUS_READY_TO_MARKET,
)
from cfh_disposition.commandcore_next_action import (
    next_action as flow_next_action,
)

ROOT = Path(__file__).resolve().parents[1]


def setup_function() -> None:
    reset_crm_clients_for_tests()
    os.environ.pop("COMMANDCORE_DEMO_MODE", None)


def teardown_function() -> None:
    setup_function()


@pytest.fixture()
def demo_crm() -> DemoCrmBackend:
    return DemoCrmBackend()


def test_lead_to_marketing_blocked_before_approval(demo_crm: DemoCrmBackend) -> None:
    created = create_lead(
        demo_crm.handle,
        seller={
            "name": "DEMO Seller Alex Example",
            "phone": "555-0199",
            "email": "alex.example@example.com",
            "demo": True,
            "notes": "DEMO DATA — fictional seller.",
        },
        property_record={
            "address": "500 DEMO Oak Lane",
            "city": "Bristol",
            "state": "VA",
            "zip": "24201",
            "demo": True,
            "notes": "DEMO DATA — fictional property facts supplied by the operator.",
        },
        deal={
            "title": "DEMO — 500 Oak Lane",
            "stage": "New Lead",
            "asking_price": "149900",
            "demo": True,
        },
    )
    assert created.ok is True
    assert created.deal_id
    assert created.contact_id
    assert created.property_id

    deal = demo_crm.handle({"action": "get", "entity": "deals", "id": created.deal_id})["record"]
    assert deal["stage"] == "New Lead"
    assert deal["links"]["contact_id"] == created.contact_id
    assert deal["links"]["property_id"] == created.property_id
    assert flow_next_action(deal).status == STATUS_NEEDS_TERMS

    terms = set_deal_terms(
        demo_crm.handle,
        deal_id=created.deal_id,
        terms={
            "asking_price": "149900",
            "offer_price": "135000",
            "arv": "175000",
            "estimated_repairs": "12000",
            "stage": "Analyzing",
            "notes": "DEMO terms entered from verified intake notes only.",
        },
    )
    assert terms.ok is True
    assert terms.record["stage"] == "Analyzing"
    assert terms.record["offer_price"] == "135000"
    assert flow_next_action(terms.record).status == STATUS_NEEDS_APPROVAL

    blocked = publish_marketing(demo_crm.handle, deal_id=created.deal_id)
    assert blocked.ok is False
    assert blocked.blocked is True
    assert blocked.published is False
    assert "approval" in blocked.message.lower()

    approval_request = request_approval(
        demo_crm.handle,
        deal_id=created.deal_id,
        offer={
            "title": "DEMO offer recommendation",
            "summary": "Internal recommendation from verified deal terms.",
            "terms": {
                "facts": {
                    "asking_price": "149900",
                    "offer_price": "135000",
                    "source": "operator_verified_demo_intake",
                }
            },
            "demo": True,
        },
    )
    assert approval_request.ok is True
    assert approval_request.record["status"] == PENDING_OFFER_STATUS
    offer_id = approval_request.record["id"]
    deal_after_request = demo_crm.handle({"action": "get", "entity": "deals", "id": created.deal_id})["record"]
    offers = demo_crm.handle({"action": "list", "entity": "offers", "limit": 50})["records"]
    assert flow_next_action(deal_after_request, offers=offers).status == STATUS_NEEDS_APPROVAL

    still_blocked = publish_marketing(demo_crm.handle, deal_id=created.deal_id)
    assert still_blocked.blocked is True
    assert still_blocked.published is False

    approved = grant_approval(
        demo_crm.handle,
        offer_id=offer_id,
        owner_name="Demo Owner",
        reason="DEMO approval for automated walkthrough",
    )
    assert approved.ok is True
    assert approved.record["status"] == APPROVED_OFFER_STATUS
    assert approved.record["owner_approved_by"] == "Demo Owner"
    deal_after_approval = demo_crm.handle({"action": "get", "entity": "deals", "id": created.deal_id})["record"]
    offers = demo_crm.handle({"action": "list", "entity": "offers", "limit": 50})["records"]
    assert flow_next_action(deal_after_approval, offers=offers).status == STATUS_READY_TO_MARKET

    published = publish_marketing(demo_crm.handle, deal_id=created.deal_id)
    assert published.ok is True
    assert published.published is True
    assert published.blocked is False
    assert published.deal["stage"] == MARKETING_STAGE
    assert published.deal.get("marketing_external_action_started") is False
    offers = demo_crm.handle({"action": "list", "entity": "offers", "limit": 50})["records"]
    assert flow_next_action(published.deal, offers=offers).status == STATUS_MARKETING_LIVE

    activities = demo_crm.handle({"action": "list", "entity": "activities", "limit": 100})["records"]
    titles = {str(item.get("title", "")) for item in activities}
    assert "Owner approval requested" in titles
    assert "Owner approved offer" in titles
    assert any("Marketing" in title for title in titles)


def test_everyday_pages_wire_demo_banner() -> None:
    """Home and core CRM pages call the shared demo banner helper."""
    for relative in (
        "pages/00_CommandCore.py",
        "pages/44_CommandCore_CRM.py",
        "pages/45_CommandCore_Deal_Record.py",
        "pages/48_CommandCore_Owner_Approvals.py",
        "pages/90_CFH_Marketing_Dispo.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "render_demo_banner" in source


def test_crm_and_deal_pages_boot_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Streamlit AppTest smoke: key everyday pages boot without Supabase secrets.

    Home (00) is checked via source wiring above; AppTest on that page alone fails
    because st.page_link targets other multipage routes outside the isolated script.
    """
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("COMMANDCORE_DEMO_MODE", "1")
    monkeypatch.setenv("APP_PASSWORD", "demo-test-password")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    reset_crm_clients_for_tests()

    # Several pages call st.page_link to sibling multipage routes; AppTest on an
    # isolated page script raises StreamlitPageNotFoundError for those links.
    # CRM and Owner Approvals stay self-contained enough for a demo-mode smoke boot.
    for relative in (
        "pages/44_CommandCore_CRM.py",
        "pages/48_CommandCore_Owner_Approvals.py",
    ):
        page = AppTest.from_file(str(ROOT / relative), default_timeout=30)
        page.session_state["authenticated"] = True
        result = page.run()
        assert not result.exception, f"{relative} raised {result.exception}"
        info_text = " ".join(str(item.value) for item in result.info)
        assert "Demo mode" in info_text
