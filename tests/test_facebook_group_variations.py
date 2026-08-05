from decimal import Decimal

from cfh_disposition.facebook_group_variations import (
    VARIATION_COUNT,
    build_facebook_group_variation,
    validate_facebook_group_variation,
    variation_index,
)
from cfh_disposition.models import OwnerFinanceProperty


def sample_property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        bedrooms=3,
        bathrooms=Decimal("1"),
        square_feet=1352,
        total_price=Decimal("94500"),
        down_payment=Decimal("2000"),
        monthly_payment=Decimal("950"),
        condition_summary="Livable property sold as-is.",
        repairs_needed="Small drywall repairs.",
        showing_instructions="Appointment required.",
        public_disclosures="Possible updating.",
    )


def test_variation_preserves_exact_facts_and_omits_total_price() -> None:
    item = sample_property()
    link = "https://tracking.example.com/?go=dwelyx&medium=facebook_groups"
    variation = build_facebook_group_variation(
        item,
        link,
        group_id="group-123",
    )

    assert item.display_address in variation.copy
    assert "$2,000" in variation.copy
    assert "$950" in variation.copy
    assert "$94,500" not in variation.copy
    assert "Small drywall repairs." in variation.copy
    assert "Possible updating." in variation.copy
    assert variation.copy.count(link) == 1
    assert validate_facebook_group_variation(variation, item, link) == []


def test_different_groups_receive_multiple_variations() -> None:
    item = sample_property()
    indexes = {
        variation_index(item.property_id, f"group-{number}")
        for number in range(1, 30)
    }
    assert len(indexes) >= 5
    assert all(0 <= index < VARIATION_COUNT for index in indexes)


def test_repost_cycle_moves_to_next_variation() -> None:
    item = sample_property()
    first = variation_index(item.property_id, "group-123", prior_post_count=0)
    second = variation_index(item.property_id, "group-123", prior_post_count=1)
    ninth = variation_index(item.property_id, "group-123", prior_post_count=8)

    assert second == (first + 1) % VARIATION_COUNT
    assert ninth == first


def test_missing_optional_condition_fields_use_safe_language() -> None:
    item = sample_property().model_copy(
        update={
            "condition_summary": "",
            "repairs_needed": "",
            "public_disclosures": "",
        }
    )
    link = "https://tracking.example.com/group"
    variation = build_facebook_group_variation(
        item,
        link,
        group_id="group-456",
    )

    assert "independently inspect and verify" in variation.copy
    assert "No repair statement was provided" in variation.copy
    assert "must be verified" in variation.copy
    assert validate_facebook_group_variation(variation, item, link) == []


def test_fact_guard_blocks_missing_link_and_prohibited_claim() -> None:
    item = sample_property()
    link = "https://tracking.example.com/group"
    safe = build_facebook_group_variation(
        item,
        link,
        group_id="group-789",
    )
    unsafe = safe.__class__(
        index=safe.index,
        label=safe.label,
        copy=safe.copy.replace(link, "") + "\nGuaranteed approval. No credit check.",
    )

    errors = validate_facebook_group_variation(unsafe, item, link)
    assert any("exactly once" in error for error in errors)
    assert any("guaranteed approval" in error.lower() for error in errors)
    assert any("no credit check" in error.lower() for error in errors)
