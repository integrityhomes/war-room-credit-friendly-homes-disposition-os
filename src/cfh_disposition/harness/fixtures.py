from __future__ import annotations

from copy import deepcopy
from typing import Any

FIXTURE_SOURCE = "commandcore_harness"
FIXTURE_FAMILY = "FIXTURE_DEAL_HARRIS_ST"

_CONTACT = {
    "id": "FIXTURE-CONTACT-HARRIS-0001",
    "name": "Harper Test Seller",
    "email": "harper.seller@example.invalid",
    "phone": "+15550000001",
    "internal_only": True,
    "fixture_source": FIXTURE_SOURCE,
}

_PROPERTY = {
    "id": "FIXTURE-PROPERTY-HARRIS-0001",
    "address": "9999 TEST Harris St, Decatur, IL 62521",
    "city": "Decatur",
    "state": "IL",
    "county": "Macon",
    "zip": "62521",
    "legal_description": "FIXTURE ONLY - Lot 1 in Harness Test Subdivision",
    "parcel_number": "FIXTURE-00-00-00-000-000",
    "internal_only": True,
    "fixture_source": FIXTURE_SOURCE,
}

_DEAL = {
    "id": "FIXTURE-DEAL-HARRIS-0001",
    "status": "Negotiating",
    "market": "Central IL",
    "lead_type": "Agent",
    "exit_mode": "Slow Flip Only",
    "asking_price": 30000,
    "rent": 1200,
    "beds": 3,
    "baths": 1,
    "sqft": 1000,
    "taxes": 1200,
    "occupancy": "Vacant",
    "livable": "Yes",
    "days_on_market": 20,
    "notes": "Harness fixture. No live outreach.",
    "arv": 100000,
    "repairs": 10000,
    "rent_source": "Fixture verified comps",
    "rent_confidence": "Strong",
    "rent_verification_needed": "No",
    "contract_type": "Illinois Contract for Deed",
    "purchase_price": "50000",
    "down_payment": "2500",
    "interest_rate": "10",
    "number_of_payments": "360",
    "first_payment_date": "2026-10-01",
    "monthly_taxes": "100",
    "monthly_insurance": "75",
    "insurance_included": "Yes",
    "contract_date": "2026-08-31",
    "payment_payee": "Fixture Seller LLC",
    "payment_address": "100 TEST Payment Way, Chesapeake, VA 23320",
    "payment_system": "Harness fake servicing portal",
    "buyer_1_name": "Taylor Test Buyer",
    "internal_only": True,
    "external_action_started": False,
    "fixture_source": FIXTURE_SOURCE,
    "links": {
        "contact_id": _CONTACT["id"],
        "property_id": _PROPERTY["id"],
    },
}

_OFFER = {
    "id": "FIXTURE-OFFER-HARRIS-0001",
    "deal_id": _DEAL["id"],
    "status": "internal_analysis",
    "starting_offer": 28000,
    "max_offer": 32000,
    "internal_only": True,
    "external_action_started": False,
    "fixture_source": FIXTURE_SOURCE,
}

_CONTRACT_DRAFT = {
    "id": "FIXTURE-CONTRACT-HARRIS-V1",
    "deal_id": _DEAL["id"],
    "document_type": "generated_contract",
    "contract_type": "Illinois Contract for Deed",
    "version": 1,
    "status": "generated_needs_review",
    "storage_bucket": "commandcore-contract-documents",
    "storage_object_path": "fixtures/FIXTURE-DEAL-HARRIS-0001/generated_contract/v1/fixture.docx",
    "internal_only": True,
    "external_action_started": False,
    "signing_started": False,
    "fixture_source": FIXTURE_SOURCE,
    "links": {"deal_id": _DEAL["id"]},
}

_TASK = {
    "id": "FIXTURE-TASK-HARRIS-0001",
    "deal_id": _DEAL["id"],
    "title": "Follow up with fixture seller",
    "status": "open",
    "internal_only": True,
    "fixture_source": FIXTURE_SOURCE,
}

_COMMUNICATION = {
    "id": "FIXTURE-COMM-HARRIS-0001",
    "deal_id": _DEAL["id"],
    "direction": "inbound",
    "channel": "sms",
    "body": "Fixture seller says the property is still available.",
    "internal_only": True,
    "fixture_source": FIXTURE_SOURCE,
}

_APPROVAL = {
    "id": "FIXTURE-APPROVAL-HARRIS-0001",
    "deal_id": _DEAL["id"],
    "status": "pending",
    "approval_type": "owner_approval",
    "internal_only": True,
    "fixture_source": FIXTURE_SOURCE,
}


def load_fixture_family() -> dict[str, Any]:
    """Return a fresh, network-free copy of the canonical Harris St fixture family."""
    return deepcopy(
        {
            "fixture_family": FIXTURE_FAMILY,
            "contact": _CONTACT,
            "property": _PROPERTY,
            "deal": _DEAL,
            "offer": _OFFER,
            "contract_draft": _CONTRACT_DRAFT,
            "task": _TASK,
            "communication": _COMMUNICATION,
            "approval": _APPROVAL,
        }
    )
