from cfh_disposition.marketplace import (
    build_meta_safe_marketplace_package,
    review_marketplace_copy,
)
from cfh_disposition.meta_marketplace_policy import (
    META_MARKETPLACE_POLICY_CHECKLIST,
    meta_marketplace_policy_errors,
)
from cfh_disposition.sample_data import SAMPLE_PROPERTIES

TRACKED_LINK = "https://tracking.example.com/?go=dwelyx&medium=marketplace"


def safe_package():
    return build_meta_safe_marketplace_package(SAMPLE_PROPERTIES[0], TRACKED_LINK)


def test_meta_safe_marketplace_package_passes_without_external_link() -> None:
    package = safe_package()
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        package.description,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert result.passed
    assert result.errors == []
    assert len(META_MARKETPLACE_POLICY_CHECKLIST) >= 12
    assert "No payment is requested through Facebook." in package.description
    assert "Equal Housing Opportunity." in package.description
    assert "not rent" in package.description.lower()
    assert "Facebook Marketplace message" in package.description
    assert "http://" not in package.description
    assert "https://" not in package.description
    assert "www." not in package.description
    assert TRACKED_LINK not in package.description
    assert f"${SAMPLE_PROPERTIES[0].down_payment:,.0f}" in package.description
    assert f"${SAMPLE_PROPERTIES[0].monthly_payment:,.0f}" in package.description
    assert f"${SAMPLE_PROPERTIES[0].total_price:,.0f}" not in package.description


def test_approval_guarantee_is_blocked() -> None:
    package = safe_package()
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        f"Everyone approved. {package.description}",
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("approved" in error.lower() for error in result.errors)


def test_fair_housing_preference_is_blocked() -> None:
    package = safe_package()
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        f"Perfect for a young couple with no children. {package.description}",
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("housing" in error.lower() or "buyer-type" in error.lower() for error in result.errors)


def test_monthly_limit_is_configurable_and_enforced() -> None:
    package = safe_package()
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        package.description,
        listings_used_this_month=5,
        monthly_limit=5,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("posting-safety limit" in error.lower() for error in result.errors)


def test_move_in_ready_claim_is_blocked() -> None:
    package = safe_package()
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        "Move-In Ready Owner-Finance Home",
        f"This move in ready property is available. {package.description}",
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("move-in ready" in error.lower() for error in result.errors)


def test_advance_fee_and_unsafe_payment_requests_are_blocked() -> None:
    text = (
        "Pay a processing fee to get approved. Send the deposit by Zelle today before viewing. "
        "Guaranteed financing is available."
    )
    errors = meta_marketplace_policy_errors(text)
    assert any("advance-fee" in error.lower() or "fee" in error.lower() for error in errors)
    assert any("payment" in error.lower() or "zelle" in error.lower() for error in errors)
    assert any("approval" in error.lower() or "financing" in error.lower() for error in errors)


def test_fraud_categories_from_meta_policy_are_blocked() -> None:
    examples = [
        "Double your money with this cash flip.",
        "Free government grant money is guaranteed.",
        "We erase bad credit and create a new credit identity.",
        "Get a cash reward when you register and send your SSN.",
        "Buy five-star reviews and ratings.",
        "Send your bank account and routing number by DM.",
        "Meta-approved offer for subscription login credentials.",
        "Use your bank account to transfer money for us.",
        "Guaranteed winning and match fixing tips.",
        "Spy camera and phone tracker available.",
    ]
    for example in examples:
        assert meta_marketplace_policy_errors(example), example


def test_required_disclosure_is_blocking() -> None:
    package = safe_package()
    incomplete = package.description.replace("No payment is requested through Facebook.", "")
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        incomplete,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("no payment" in error.lower() for error in result.errors)


def test_external_link_is_blocked() -> None:
    package = safe_package()
    description = f"{package.description}\n{TRACKED_LINK}"
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        description,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("website links" in error.lower() or "dwelyx" in error.lower() for error in result.errors)


def test_exact_public_financial_terms_are_required() -> None:
    package = safe_package()
    incomplete = package.description.replace(f"${SAMPLE_PROPERTIES[0].down_payment:,.0f}", "$1")
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        incomplete,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("exact down payment" in error.lower() for error in result.errors)


def test_public_purchase_price_is_blocked_for_marketplace() -> None:
    package = safe_package()
    description = (
        f"{package.description}\nPurchase price: ${SAMPLE_PROPERTIES[0].total_price:,.0f}"
    )
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        description,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("remove the total purchase price" in error.lower() for error in result.errors)


def test_not_rent_clarity_is_required() -> None:
    package = safe_package()
    incomplete = package.description.replace("The monthly payment shown is not rent.", "")
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        incomplete,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("not rent" in error.lower() for error in result.errors)


def test_facebook_message_call_to_action_is_required() -> None:
    package = safe_package()
    incomplete = package.description.replace(
        "Send us a Facebook Marketplace message for complete purchase terms, property questions, and next steps.",
        "Contact us for details.",
    )
    result = review_marketplace_copy(
        SAMPLE_PROPERTIES[0],
        package.title,
        incomplete,
        listings_used_this_month=0,
        tracked_dwelyx_link=TRACKED_LINK,
    )
    assert not result.passed
    assert any("facebook marketplace message" in error.lower() for error in result.errors)


def test_validator_handles_legacy_string_values_without_typeerror() -> None:
    item = SAMPLE_PROPERTIES[0].model_copy(deep=True)
    object.__setattr__(item, "total_price", "100000")
    object.__setattr__(item, "down_payment", "5000")
    object.__setattr__(item, "monthly_payment", "1200")
    object.__setattr__(item, "condition_summary", None)
    object.__setattr__(item, "repairs_needed", None)
    object.__setattr__(item, "public_disclosures", None)

    package = build_meta_safe_marketplace_package(item)
    result = review_marketplace_copy(
        item,
        package.title,
        package.description,
        listings_used_this_month="0",
        monthly_limit="5",
    )

    assert isinstance(result.errors, list)
    assert any("public disclosures" in error.lower() for error in result.errors)
