from cfh_disposition.commandcore_completion_controls import verified_final_outcome


def valid_outcome() -> dict:
    return {
        "status": "completed",
        "transaction_type": "owner_finance_completion",
        "completion_verified": True,
        "buyer_contract_executed": True,
        "completion_effective_at": "2026-08-29T16:00:00Z",
    }


def test_verified_final_outcome_requires_all_evidence() -> None:
    assert verified_final_outcome(valid_outcome()) is True


def test_marketing_sold_flag_is_not_final_outcome() -> None:
    record = valid_outcome()
    record["transaction_type"] = "property_marketing_sold"
    assert verified_final_outcome(record) is False


def test_unverified_outcome_does_not_complete_deal() -> None:
    record = valid_outcome()
    record["completion_verified"] = False
    assert verified_final_outcome(record) is False


def test_buyer_contract_execution_is_required() -> None:
    record = valid_outcome()
    record["buyer_contract_executed"] = False
    assert verified_final_outcome(record) is False


def test_completion_timestamp_is_required() -> None:
    record = valid_outcome()
    record["completion_effective_at"] = ""
    assert verified_final_outcome(record) is False
