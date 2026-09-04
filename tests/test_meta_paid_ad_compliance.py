from dataclasses import replace
from decimal import Decimal

from cfh_disposition.listing_compliance import ComplianceResultState
from cfh_disposition.models import OwnerFinanceProperty
from cfh_disposition.paid_traffic_channels import (
    build_paid_traffic_package,
    review_paid_traffic_package,
)


def property_record() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        address="945 W Packard St",
        city="Decatur",
        state="IL",
        zip_code="62522",
        total_price=Decimal("79900"),
        down_payment=Decimal("3500"),
        monthly_payment=Decimal("995"),
    )


def package():
    return build_paid_traffic_package(
        property_record(),
        channel_key="meta_ads",
        channel_name="Meta Housing Ads",
        tracked_link="https://tracking.example.com/?medium=meta_ads",
        campaign_name="decatur_meta",
        daily_budget=Decimal("20"),
        monthly_budget_cap=Decimal("600"),
    )


def test_meta_final_copy_requires_approval_but_does_not_execute() -> None:
    result = review_paid_traffic_package(package(), property_record())

    assert result.result == ComplianceResultState.APPROVAL_REQUIRED
    assert result.approval_required is True
    assert result.publication_mode == "Approval Required"
    assert result.external_action_started is False
    assert not result.blockers


def test_meta_final_copy_blocks_discrimination_and_financing_claims() -> None:
    original = package()
    unsafe = replace(
        original,
        primary_text_options=(
            f"Families only in a safe neighborhood. Guaranteed approval. {original.primary_text_options[0]}",
            *original.primary_text_options[1:],
        ),
    )
    result = review_paid_traffic_package(unsafe, property_record())

    assert result.result == ComplianceResultState.BLOCKED
    assert any("housing" in reason.lower() or "property" in reason.lower() for reason in result.blockers)
    assert any("approval" in reason.lower() for reason in result.blockers)


def test_meta_final_copy_blocks_missing_disclosure_and_changed_terms() -> None:
    original = package()
    unsafe = replace(
        original,
        description="Current property details and next steps.",
        primary_text_options=tuple(text.replace("$3,500", "$999") for text in original.primary_text_options),
    )
    result = review_paid_traffic_package(unsafe, property_record())

    assert result.result == ComplianceResultState.BLOCKED
    assert any("disclosure" in reason.lower() for reason in result.blockers)
    assert any("down payment" in reason.lower() or "$999" in reason for reason in result.blockers)
