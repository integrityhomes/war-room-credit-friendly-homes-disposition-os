from cfh_disposition.marketplace import review_marketplace_copy
from cfh_disposition.sample_data import SAMPLE_PROPERTIES


def test_compliant_marketplace_copy_passes() -> None:
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        "Owner-Financed Home Available in Saltville",
        "Owner-finance opportunity with accurate property terms and condition details. "
        "Please review the complete property page and request a callback for next steps. "
        "Approval and terms are subject to review.",
        listings_used_this_month=0,
    )
    assert result.passed


def test_approval_guarantee_is_blocked() -> None:
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        "Owner-Financed Home",
        "Everyone approved. This description is otherwise long enough to pass the minimum-length warning requirement. "
        "Contact us today for property details and a showing appointment.",
        listings_used_this_month=0,
    )
    assert not result.passed
    assert any("guarantee" in error.lower() for error in result.errors)


def test_fair_housing_preference_is_blocked() -> None:
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        "Home for Sale",
        "Perfect for a young couple with no children. This description is extended to ensure length is not the reason for failure.",
        listings_used_this_month=0,
    )
    assert not result.passed
    assert len(result.errors) >= 1


def test_monthly_limit_is_configurable_and_enforced() -> None:
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        "Owner-Financed Home in Saltville",
        "Accurate owner-finance property information with condition, terms, and disclosures available for review. "
        "Request a callback to learn more.",
        listings_used_this_month=5,
        monthly_limit=5,
    )
    assert not result.passed


def test_move_in_ready_claim_is_blocked() -> None:
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        "Move-In Ready Owner-Financed Home",
        "This move in ready property is available with owner-finance terms. Review all condition details, disclosures, and terms before proceeding.",
        listings_used_this_month=0,
    )
    assert not result.passed
    assert any("move-in ready" in error.lower() for error in result.errors)
