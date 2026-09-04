from datetime import UTC, datetime
from decimal import Decimal

from cfh_disposition.listing_compliance import (
    SHARED_COMPLIANCE_POLICY_VERSION,
    ComplianceResultState,
    compliance_content_hash,
    review_shared_compliance,
)
from cfh_disposition.models import OwnerFinanceProperty


def property_record() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="101 Test Street",
        city="Bristol",
        state="VA",
        zip_code="24201",
        total_price=Decimal("100000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1200"),
    )


def review(content: str, *, approval_required: bool = False):
    return review_shared_compliance(
        channel="test_housing",
        content=content,
        approval_required=approval_required,
        publication_mode="Internal Review",
        checked_at=datetime(2026, 9, 4, tzinfo=UTC),
    )


def test_result_contract_is_versioned_deterministic_and_safe() -> None:
    result = review("Factual housing information.")

    assert result.result == ComplianceResultState.PASSED
    assert result.policy_version == SHARED_COMPLIANCE_POLICY_VERSION
    assert result.content_hash == compliance_content_hash("test_housing", "Factual housing information.")
    assert result.policy_checked_at == datetime(2026, 9, 4, tzinfo=UTC)
    assert result.external_action_started is False
    assert "execution.no_automatic_action" in result.rule_identifiers
    assert not ({"token", "password", "secret"} & set(result.model_dump()))


def test_approval_and_warning_states_are_plain_english() -> None:
    required = review("Factual housing information.", approval_required=True)
    warned = review_shared_compliance(
        channel="test_housing",
        content="Factual housing information.",
        approval_required=False,
        publication_mode="Assisted Posting",
        required_disclosures=(),
        checked_at=datetime(2026, 9, 4, tzinfo=UTC),
    ).model_copy(update={"warnings": ("Review the final layout.",), "result": ComplianceResultState.PASSED_WITH_WARNINGS})

    assert required.result == ComplianceResultState.APPROVAL_REQUIRED
    assert "Human approval" in required.warnings[0]
    assert warned.result == ComplianceResultState.PASSED_WITH_WARNINGS


def test_fair_housing_and_financing_claims_are_blocked() -> None:
    examples = (
        "Families only in a safe neighborhood.",
        "Perfect for a young couple with no children.",
        "Christian buyers preferred.",
        "White buyers only.",
        "Disabled buyers are not accepted.",
        "Guaranteed approval with no credit check.",
    )
    for content in examples:
        result = review(content)
        assert result.result == ComplianceResultState.BLOCKED, content
        assert result.blockers


def test_sensitive_data_and_misleading_claims_are_blocked() -> None:
    result = review("Send your SSN and bank account to receive free government grant money.")

    assert result.result == ComplianceResultState.BLOCKED
    assert "privacy.sensitive_data_request" in result.rule_identifiers
    assert "claims.misleading_assistance" in result.rule_identifiers


def test_property_facts_disclosures_and_unverified_money_are_blocking() -> None:
    result = review_shared_compliance(
        channel="meta_ads",
        content="101 Test Street, Bristol, VA 24201. $5,000 down and $1,200 monthly. Bonus $999.",
        property_record=property_record(),
        required_disclosures=("Approval is not guaranteed.",),
        approval_required=True,
        publication_mode="Approval Required",
        checked_at=datetime(2026, 9, 4, tzinfo=UTC),
    )

    assert result.result == ComplianceResultState.BLOCKED
    assert any("Required disclosure" in message for message in result.blockers)
    assert any("$999" in message for message in result.blockers)
