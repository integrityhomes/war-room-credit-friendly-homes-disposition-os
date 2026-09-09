from __future__ import annotations

from cfh_disposition.contract_deal_facts import assemble_contract_facts
from cfh_disposition.missouri_contract_generation import _build_missouri_inputs, is_missouri_afd


def _missouri_facts() -> dict:
    return {
        "contract_type": "Missouri Agreement for Deed",
        "state": "MO",
        "property_address": "123 Main St, Saint Louis, MO 63101",
        "seller_name": "Example Seller LLC",
        "seller_mailing_address": "456 Seller Rd, Saint Louis, MO 63102",
        "buyer_1_name": "Buyer One",
        "buyer_2_name": "Buyer Two",
        "buyer_1_email": "one@example.com",
        "buyer_2_email": "two@example.com",
        "buyer_1_phone": "555-1111",
        "buyer_2_phone": "555-2222",
        "contract_date": "2026-08-30",
        "first_payment_date": "2026-10-01",
        "purchase_price": "50000",
        "down_payment": "2500",
        "amount_financed": "47500",
        "interest_rate": "10",
        "number_of_payments": "360",
        "monthly_principal_interest": "416.79",
        "monthly_taxes": "75",
        "monthly_payment": "516.79",
        "monthly_servicing_fee": "25",
        "conversion_rent": "900",
        "payment_payee": "Example Seller LLC",
        "payment_address": "456 Seller Rd, Saint Louis, MO 63102",
        "payment_system": "Buildium property management website",
        "late_fee_percent": "10",
        "grace_period_days": "5",
        "apr": "10",
        "finance_charge": "102544.4",
        "total_of_payments": "150044.4",
        "buyer_use_primary": False,
        "buyer_use_investment": True,
        "buyer_use_fix_flip": False,
        "buyer_use_family": False,
        "buyer_use_short_term": False,
        "buyer_use_landlord": True,
        "buyer_use_other": False,
        "buyer_use_other_text": "",
    }


def test_missouri_classifier_requires_missouri_agreement_for_deed() -> None:
    assert is_missouri_afd("Missouri Agreement for Deed") is True
    assert is_missouri_afd("Missouri AFD") is True
    assert is_missouri_afd("Illinois Contract for Deed") is False


def test_missouri_generation_inputs_preserve_proven_renderer_fields() -> None:
    context, schedule = _build_missouri_inputs(_missouri_facts())

    assert context["PROPERTY_CITY"] == "Saint Louis"
    assert context["MONTHLY_SERVICING_FEE"] == "$25.00"
    assert context["TOTAL_MONTHLY_PAYMENT"] == "$516.79"
    assert context["CONVERSION_RENT"] == "$900.00"
    assert context["USE_INVESTMENT"] == "[X]"
    assert context["USE_LANDLORD"] == "[X]"
    assert context["USE_PRIMARY"] == "[ ]"
    assert context["FINAL_PAYMENT_DATE"] == "September 1, 2056"
    assert len(schedule) == 360


def test_missouri_defaults_match_proven_standalone_behavior() -> None:
    facts = _missouri_facts()
    facts["monthly_servicing_fee"] = ""
    facts["conversion_rent"] = ""
    facts["late_fee_percent"] = ""
    facts["grace_period_days"] = ""

    context, _ = _build_missouri_inputs(facts)

    assert context["MONTHLY_SERVICING_FEE"] == "$25.00"
    assert context["CONVERSION_RENT"] == "$516.79"
    assert context["LATE_FEE_PERCENT"] == "10%"
    assert context["GRACE_PERIOD_DAYS"] == "5"


def test_canonical_deal_facts_carry_missouri_only_fields() -> None:
    facts, missing = assemble_contract_facts(
        deal={
            "contract_type": "Missouri Agreement for Deed",
            "purchase_price": "50000",
            "conversion_rent": "900",
            "monthly_servicing_fee": "25",
            "buyer_1_name": "Buyer One",
            "buyer_use_investment": True,
            "buyer_use_landlord": True,
            "buyer_use_other_text": "",
        },
        seller={"name": "Example Seller LLC", "mailing_address": "456 Seller Rd, Saint Louis, MO 63102"},
        property_record={
            "state": "MO",
            "address": "123 Main St, Saint Louis, MO 63101",
            "legal_description": "Lot 1",
            "parcel_number": "19-00-000-0000",
        },
    )

    assert missing == []
    assert facts["conversion_rent"] == "900"
    assert facts["monthly_servicing_fee"] == "25"
    assert facts["buyer_use_investment"] is True
    assert facts["buyer_use_landlord"] is True
