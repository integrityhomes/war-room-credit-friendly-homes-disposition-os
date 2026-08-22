from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from .models import OwnerFinanceProperty, PropertyStatus


class PropertyFactLockError(RuntimeError):
    """Raised when a downstream marketing artifact no longer matches property truth."""


MARKETABLE_PROPERTY_STATUSES = frozenset(
    {
        PropertyStatus.READY,
        PropertyStatus.LIVE,
    }
)

LOCKED_MARKETING_FACTS = (
    "total_price",
    "down_payment",
    "monthly_payment",
    "bedrooms",
    "bathrooms",
    "status",
    "available_date",
)


def _decimal_text(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def property_fact_snapshot(property_record: OwnerFinanceProperty) -> dict[str, str | int]:
    """Return the immutable marketing facts downstream surfaces must inherit."""
    return {
        "property_id": str(property_record.property_id),
        "total_price": _decimal_text(property_record.total_price),
        "down_payment": _decimal_text(property_record.down_payment),
        "monthly_payment": _decimal_text(property_record.monthly_payment),
        "bedrooms": property_record.bedrooms if property_record.bedrooms is not None else -1,
        "bathrooms": _decimal_text(property_record.bathrooms),
        "status": property_record.status.value,
        "available_date": property_record.available_date,
    }


def property_fact_signature(property_record: OwnerFinanceProperty) -> str:
    """Create a stable signature used to invalidate stale VA tasks and marketing packages."""
    payload = json.dumps(
        property_fact_snapshot(property_record),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def ensure_property_facts_current(
    property_record: OwnerFinanceProperty,
    expected_signature: str,
) -> None:
    if not expected_signature:
        raise PropertyFactLockError(
            "This marketing task predates the property fact-lock. Regenerate it from the current property record before posting."
        )
    current_signature = property_fact_signature(property_record)
    if current_signature != expected_signature:
        raise PropertyFactLockError(
            "The property facts changed after this marketing task was created. Regenerate the task from the central property record before posting."
        )


def ensure_property_is_marketable(property_record: OwnerFinanceProperty) -> None:
    if property_record.status not in MARKETABLE_PROPERTY_STATUSES:
        raise PropertyFactLockError(
            f"Marketing is blocked because this property is {property_record.status.value}. Update the central property status before creating or posting marketing."
        )
