from decimal import Decimal

from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.nextdoor import (
    NEXTDOOR_BODY_LIMIT,
    NEXTDOOR_CTA_LIMIT,
    NEXTDOOR_HEADLINE_LIMIT,
    NEXTDOOR_IMAGE_SPECS,
    build_nextdoor_package,
    validate_nextdoor_copy,
)


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        total_price=Decimal("94500"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        condition_summary="Livable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        public_disclosures="Possible updating.",
    )


def test_nextdoor_package_preserves_property_facts_and_hides_total_price() -> None:
    item = sample_property()
    tracked_link = "https://tracking.example.com/?medium=nextdoor"
    package = build_nextdoor_package(item, tracked_link)

    for copy in [package.business_post_body, package.paid_ad_body]:
        assert validate_nextdoor_copy(copy, item, tracked_link) == []
        assert item.display_address in copy
        assert "$2,000" in copy
        assert "$950" in copy
        assert "$94,500" not in copy
        assert copy.count(tracked_link) == 1
        assert "not rent" in copy.lower()
        assert "subject to review and verification" in copy.lower()
        assert "equal housing opportunity" in copy.lower()


def test_nextdoor_package_respects_creative_limits() -> None:
    package = build_nextdoor_package(
        sample_property(),
        "https://tracking.example.com/?medium=nextdoor",
    )

    assert len(package.business_post_title) <= NEXTDOOR_HEADLINE_LIMIT
    assert len(package.paid_ad_headline) <= NEXTDOOR_HEADLINE_LIMIT
    assert len(package.business_post_body) <= NEXTDOOR_BODY_LIMIT
    assert len(package.paid_ad_body) <= NEXTDOOR_BODY_LIMIT
    assert len(package.paid_ad_cta) <= NEXTDOOR_CTA_LIMIT
    assert "1200 × 628" in NEXTDOOR_IMAGE_SPECS
    assert "1200 × 1200" in NEXTDOOR_IMAGE_SPECS


def test_nextdoor_guard_blocks_risky_housing_language_and_bad_links() -> None:
    item = sample_property()
    tracked_link = "https://tracking.example.com/?medium=nextdoor"
    package = build_nextdoor_package(item, tracked_link)

    risky_copy = package.business_post_body.replace(
        "Owner-finance home information",
        "Guaranteed approval in a safe neighborhood",
    )
    missing_link = package.business_post_body.replace(tracked_link, "")

    risky_errors = validate_nextdoor_copy(risky_copy, item, tracked_link)
    link_errors = validate_nextdoor_copy(missing_link, item, tracked_link)

    assert any("guaranteed approval" in error.lower() for error in risky_errors)
    assert any("safe neighborhood" in error.lower() for error in risky_errors)
    assert any("tracked dwelyx link" in error.lower() for error in link_errors)


def test_nextdoor_instructions_require_manual_verified_operation() -> None:
    package = build_nextdoor_package(
        sample_property(),
        "https://tracking.example.com/?medium=nextdoor",
    )
    combined = " ".join(package.publication_instructions).lower()

    assert "verified nextdoor business page" in combined
    assert "manual" in combined
    assert "manager approval" in combined
    assert "zip-code" in combined
    assert "protected" in combined
