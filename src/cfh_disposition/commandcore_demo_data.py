"""Clearly fictional DEMO seed data for local CommandCore CRM demo mode."""

from __future__ import annotations

from typing import Any

DEMO_BANNER = (
    "Demo mode — connect Supabase to use real data. "
    "See docs/SETUP_SUPABASE.md for setup steps."
)

DEMO_CONNECT_NEXT_STEP = (
    "Add SUPABASE_URL and SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY) "
    "in Streamlit Secrets, then follow docs/SETUP_SUPABASE.md."
)


def build_demo_crm_seed() -> dict[str, list[dict[str, Any]]]:
    """Return seeded CRM entities labeled as DEMO with fake addresses only."""
    contact = {
        "id": "demo-contact-001",
        "name": "DEMO Seller Jordan Sample",
        "first_name": "Jordan",
        "last_name": "Sample",
        "phone": "555-0101",
        "email": "jordan.sample@example.com",
        "source": "demo",
        "external_id": "demo-seller-001",
        "notes": "DEMO DATA — fictional seller for local walkthroughs.",
        "demo": True,
    }
    property_record = {
        "id": "demo-property-001",
        "address": "101 DEMO Sample Ridge Road",
        "city": "Saltville",
        "state": "VA",
        "zip": "24370",
        "county": "Smyth",
        "bedrooms": 2,
        "bathrooms": 1,
        "source": "demo",
        "external_id": "demo-property-001",
        "notes": "DEMO DATA — fictional property. Do not use for marketing claims.",
        "demo": True,
    }
    deal = {
        "id": "demo-deal-001",
        "title": "DEMO — 101 Sample Ridge Road",
        "status": "Active",
        "stage": "New Lead",
        "assigned_to": "Demo Operator",
        "asking_price": "119900",
        "offer_price": "",
        "arv": "",
        "estimated_repairs": "",
        "source": "demo",
        "external_id": "demo-deal-001",
        "notes": "DEMO DATA — starter lead for the everyday Leads → Deal path.",
        "demo": True,
        "links": {
            "contact_id": "demo-contact-001",
            "property_id": "demo-property-001",
        },
    }
    return {
        "contacts": [contact],
        "properties": [property_record],
        "deals": [deal],
        "activities": [],
        "communications": [],
        "tasks": [],
        "offers": [],
        "documents": [],
        "transactions": [],
    }
