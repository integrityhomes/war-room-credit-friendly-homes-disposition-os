from cfh_disposition.contract_review_facts import review_facts_from_verified_contract_facts


def test_reader_reuses_verified_builder_fact_values() -> None:
    rows = review_facts_from_verified_contract_facts(
        {
            "seller_name": "Jane Smith",
            "property_address": "123 Main Street",
            "purchase_price": "45000",
            "buyer_1_name": "Alex Buyer",
            "insurance_included": "No",
            "approved_deal_terms_only": True,
        }
    )

    by_key = {row.key: row for row in rows}
    assert by_key["seller_name"].expected_value == "Jane Smith"
    assert by_key["property_address"].expected_value == "123 Main Street"
    assert by_key["purchase_price"].expected_value == "45000"
    assert by_key["insurance_included"].expected_value == "No"
    assert "approved_deal_terms_only" not in by_key
    assert by_key["legal_description"].expected_value == ""
