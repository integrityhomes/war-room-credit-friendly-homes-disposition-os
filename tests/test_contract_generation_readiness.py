from cfh_disposition.contract_deal_facts import assemble_contract_facts
from cfh_disposition.contract_generation_readiness import generation_readiness


def _illinois_ready_facts() -> dict[str, str]:
    return {
        "seller_name": "Seller LLC",
        "seller_mailing_address": "1 Seller Way, Decatur, IL 62521",
        "seller_formation_state": "Illinois",
        "property_address": "123 Main St, Decatur, IL 62521",
        "property_county": "Macon",
        "legal_description": "Lot 7",
        "parcel_number": "12-34-567-890",
        "buyer_1_name": "Buyer One",
        "purchase_price": "45000",
        "down_payment": "2500",
        "interest_rate": "10",
        "number_of_payments": "360",
        "first_payment_date": "2026-10-01",
        "monthly_taxes": "120",
        "insurance_included": "Yes",
        "contract_date": "2026-09-01",
        "payment_payee": "Seller LLC",
        "payment_address": "1 Seller Way, Decatur, IL 62521",
        "payment_system": "Online portal",
    }


def test_illinois_cfd_reports_ready_only_when_required_generation_facts_exist() -> None:
    facts = _illinois_ready_facts()
    ready = generation_readiness("Illinois Contract for Deed", facts)
    assert ready.ready is True
    assert ready.missing_fields == ()

    facts["property_county"] = ""
    blocked = generation_readiness("Illinois Contract for Deed", facts)
    assert blocked.ready is False
    assert "Illinois county" in blocked.missing_fields


def test_unknown_contract_package_never_guesses_generation_rules() -> None:
    status = generation_readiness("Custom Attorney Agreement", {})
    assert status.ready is False
    assert "Approved generation rules" in status.missing_fields[0]


def test_deal_facts_expose_v14_fields_without_inventing_values() -> None:
    facts, _missing = assemble_contract_facts(
        deal={
            "contract_type": "Illinois Contract for Deed",
            "offer_price": "45000",
            "buyer_1_name": "Buyer One",
            "term_months": "360",
            "payment_system": "Online portal",
            "insurance_included": "Yes",
        },
        seller={
            "name": "Seller LLC",
            "mailing_address": "1 Seller Way",
            "formation_state": "Illinois",
        },
        property_record={
            "address": "123 Main St",
            "state": "Illinois",
            "county": "Macon",
            "legal_description": "Lot 7",
            "parcel_id": "12-34-567-890",
        },
    )

    assert facts["property_county"] == "Macon"
    assert facts["seller_mailing_address"] == "1 Seller Way"
    assert facts["seller_formation_state"] == "Illinois"
    assert facts["number_of_payments"] == "360"
    assert facts["payment_system"] == "Online portal"
    assert facts["monthly_taxes"] == ""
