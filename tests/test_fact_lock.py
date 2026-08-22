from decimal import Decimal

import pytest

from cfh_disposition.fact_lock import (
    PropertyFactLockError,
    ensure_property_facts_current,
    ensure_property_is_marketable,
    property_fact_signature,
    property_fact_snapshot,
)
from cfh_disposition.models import OwnerFinanceProperty, PropertyStatus


def _property() -> OwnerFinanceProperty:
    return OwnerFinanceProperty(
        status=PropertyStatus.READY,
        address="123 Main St",
        city="Decatur",
        state="IL",
        zip_code="62521",
        bedrooms=3,
        bathrooms=Decimal("1.5"),
        total_price=Decimal("85000"),
        down_payment=Decimal("5000"),
        monthly_payment=Decimal("1100"),
        available_date="2026-09-01",
    )


def test_fact_snapshot_contains_locked_property_truth():
    snapshot = property_fact_snapshot(_property())
    assert snapshot["total_price"] == "85000"
    assert snapshot["down_payment"] == "5000"
    assert snapshot["monthly_payment"] == "1100"
    assert snapshot["bedrooms"] == 3
    assert snapshot["status"] == PropertyStatus.READY.value


def test_fact_signature_changes_when_locked_fact_changes():
    original = _property()
    signature = property_fact_signature(original)
    changed = original.model_copy(update={"monthly_payment": Decimal("1200")})
    assert property_fact_signature(changed) != signature


def test_stale_marketing_artifact_is_blocked():
    original = _property()
    signature = property_fact_signature(original)
    changed = original.model_copy(update={"down_payment": Decimal("6500")})
    with pytest.raises(PropertyFactLockError):
        ensure_property_facts_current(changed, signature)


def test_marketing_is_blocked_for_sold_or_filled_property():
    for status in (PropertyStatus.SOLD, PropertyStatus.FILLED, PropertyStatus.PENDING, PropertyStatus.PAUSED):
        with pytest.raises(PropertyFactLockError):
            ensure_property_is_marketable(_property().model_copy(update={"status": status}))


def test_ready_and_live_properties_are_marketable():
    ensure_property_is_marketable(_property())
    ensure_property_is_marketable(_property().model_copy(update={"status": PropertyStatus.LIVE}))
