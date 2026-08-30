# ruff: noqa: I001
import pytest

from cfh_disposition.contract_deal_facts import (
    ContractFactsError,
    assemble_contract_facts,
    contract_prep_document,
)


def sample_deal() -> dict:
    return {
        "contract_type": "Illinois Contract for Deed",
        "purchase_price": "42000",
        "buyer_1_name": "Buyer One",
        "down_payment": "2500",
        "interest_rate": "12",
        "monthly_payment": "895",
        "insurance_included": "Yes",
    }


def sample_property() -> dict:
    return {
        "address": "123 Main St",
        "city": "Decatur",
        "state": "IL",
        "zip": "62521",
        "legal_description": "Lot 1",
        "parcel_number": "12-34-567-890",
    }


def test_contract_facts_use_existing_deal_and_property_values() -> None:
    facts, missing = assemble_contract_facts(
        deal=sample_deal(),
        seller={"name": "Seller LLC", "email": "seller@example.com"},
        property_record=sample_property(),
    )

    assert missing == []
    assert facts["contract_type"] == "Illinois Contract for Deed"
    assert facts["property_address"] == "123 Main St"
    assert facts["seller_name"] == "Seller LLC"
    assert facts["buyer_1_name"] == "Buyer One"
    assert facts["insurance_included"] == "Yes"
    assert facts["approved_deal_terms_only"] is True


def test_contract_facts_never_guess_contract_type_or_state() -> None:
    with pytest.raises(ContractFactsError):
        assemble_contract_facts(deal={}, seller=None, property_record=sample_property())

    property_without_state = {**sample_property(), "state": ""}
    with pytest.raises(ContractFactsError):
        assemble_contract_facts(
            deal=sample_deal(),
            seller=None,
            property_record=property_without_state,
        )


def test_complete_facts_can_move_to_approved_template_matching() -> None:
    record = contract_prep_document(
        deal_id="deal-1",
        deal=sample_deal(),
        seller={"name": "Seller LLC"},
        property_record=sample_property(),
    )

    assert record["status"] == "needs_approved_legal_template"
    assert record["generation_ready"] is True
    assert record["missing_facts"] == []


def test_missing_legal_or_party_facts_are_visible_and_block_generation_readiness() -> None:
    property_record = {**sample_property(), "legal_description": "", "parcel_number": ""}
    deal = {**sample_deal(), "buyer_1_name": ""}
    record = contract_prep_document(
        deal_id="deal-1",
        deal=deal,
        seller=None,
        property_record=property_record,
    )

    assert record["status"] == "needs_missing_facts"
    assert record["generation_ready"] is False
    assert set(record["missing_facts"]) == {
        "seller name",
        "buyer 1 legal name",
        "legal description",
        "parcel number",
    }
    assert record["legal_terms_generated"] is False
    assert record["legal_terms_changed"] is False
    assert record["signing_started"] is False
    assert record["external_action_started"] is False
    assert record["links"]["deal_id"] == "deal-1"
